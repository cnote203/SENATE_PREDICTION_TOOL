"""Fit each dimension's formula to real roll calls.

Model (pooled probit, one per dimension k):

    P(senator i votes on the +2 side of item j)
        = Phi( alpha_j + b1*d1_i + b2*d1_i^2 + b3*d2_i + gamma*CP_ij + u_i )

    alpha_j   item cutpoint (how hard the item is to support)
    b1..b3    shared ideology mapping: this replaces the hand-set formula
    gamma     effect of being in the President's party; only estimated when the
              dimension has items from both a Democratic and a Republican White House
    u_i       senator's deviation from the mapping, u_i ~ N(0, sigma^2)

Design choices follow Clinton, Jackman & Rivers (2004) and Lauderdale & Clark
(2014): few items per issue, so deviations are shrunk toward the ideology
prediction. Fitting is MAP with Gaussian priors (a light ridge), so small item
sets stay stable.

- Items whose losing side is under LOPSIDED_CUTOFF of yea+nay are dropped.
- Near-replicate items (the same family, e.g. the Iran war powers series) are
  down-weighted by 1/sqrt(family size) so one series cannot dominate.
- Present and Not Voting are treated as missing.

The latent scale is then mapped to the -2..+2 score scale with a fixed linear
transform stored in the calibration file, and sigma becomes the score SD floor.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import log_ndtr
from scipy.stats import norm

LOPSIDED_CUTOFF = 0.025
PRIOR_SD_ALPHA = 2.0
PRIOR_SD_BETA = 2.0
PRIOR_SD_GAMMA = 1.5
# Score = SCORE_K * (latent - mean) / sd, so +-2 sits about 2.2 SD from the mean.
# AUDIT: a scale convention, not an estimate.
SCORE_K = 0.9
SUGGEST_OVERRIDE_MIN = 0.75  # score units

FEATURES = ["d1", "d1_sq", "d2"]


@dataclass
class DimensionFit:
    dimension: str
    beta: dict
    gamma: float
    gamma_identified: bool
    items: pd.DataFrame
    sigma_latent: float
    scale_mean: float
    scale_sd: float
    deviations: pd.DataFrame
    cv: dict

    @property
    def sigma_score(self) -> float:
        return SCORE_K * self.sigma_latent / self.scale_sd

    def to_dict(self) -> dict:
        return {
            "fitted": True,
            "beta": self.beta,
            "gamma": self.gamma,
            "gamma_identified": self.gamma_identified,
            "sigma_latent": self.sigma_latent,
            "sigma_score": self.sigma_score,
            "scale": {"mean": self.scale_mean, "sd": self.scale_sd, "k": SCORE_K},
            "cv": self.cv,
            "items": self.items.to_dict(orient="records"),
        }


def build_dataset(items: pd.DataFrame, votes: pd.DataFrame, ideology: pd.DataFrame) -> pd.DataFrame:
    """Join coded votes to item metadata and ideology.

    items:    one row per roll call: item_id, dimension, plus_side, family, president_party
    votes:    item_id, bioguide_id, party, vote_cast, yea (1/0/NaN)
    ideology: bioguide_id, nominate_dim1, nominate_dim2
    """
    df = votes.merge(items, on="item_id").merge(
        ideology.rename(columns={"nominate_dim1": "d1", "nominate_dim2": "d2"}), on="bioguide_id"
    )
    df = df[df["yea"].notna() & df["d1"].notna()].copy()
    df["d2"] = df["d2"].fillna(0.0)
    df["y"] = np.where(df["plus_side"].str.lower() == "yea", df["yea"], 1 - df["yea"])
    # AUDIT: independents are counted with the Democrats (King and Sanders caucus with them).
    party = df["party"].replace({"I": "D", "ID": "D"})
    df["cp"] = (party == df["president_party"]).astype(float)
    df["d1_sq"] = df["d1"] ** 2
    return df


def drop_lopsided(df: pd.DataFrame, cutoff: float = LOPSIDED_CUTOFF) -> tuple[pd.DataFrame, pd.DataFrame]:
    share = df.groupby("item_id")["yea"].agg(lambda s: min(s.mean(), 1 - s.mean()))
    kept = share[share >= cutoff].index
    return df[df["item_id"].isin(kept)].copy(), share.rename("minority_share").reset_index()


def _negloglik(params, y, w, item_idx, X, n_items, prior_sd):
    alpha, beta = params[:n_items], params[n_items:]
    eta = alpha[item_idx] + X @ beta
    q = 2 * y - 1
    z = q * eta
    ll = log_ndtr(z)
    lam = np.exp(norm.logpdf(z) - ll)
    g_eta = -w * q * lam
    f = -(w * ll).sum() + 0.5 * (alpha ** 2).sum() / PRIOR_SD_ALPHA ** 2 \
        + 0.5 * ((beta / prior_sd) ** 2).sum()
    grad = np.concatenate([
        np.bincount(item_idx, weights=g_eta, minlength=n_items) + alpha / PRIOR_SD_ALPHA ** 2,
        X.T @ g_eta + beta / prior_sd ** 2,
    ])
    return f, grad


def _fit_pooled(df: pd.DataFrame, use_gamma: bool):
    item_ids = sorted(df["item_id"].unique())
    idx = df["item_id"].map({k: i for i, k in enumerate(item_ids)}).to_numpy()
    cols = FEATURES + (["cp"] if use_gamma else [])
    X = df[cols].to_numpy(float)
    prior_sd = np.array([PRIOR_SD_BETA] * len(FEATURES) + ([PRIOR_SD_GAMMA] if use_gamma else []))
    x0 = np.zeros(len(item_ids) + len(cols))
    res = minimize(
        _negloglik, x0, jac=True, method="L-BFGS-B",
        args=(df["y"].to_numpy(float), df["w"].to_numpy(float), idx, X, len(item_ids), prior_sd),
    )
    alpha = dict(zip(item_ids, res.x[: len(item_ids)]))
    beta = dict(zip(cols, res.x[len(item_ids):]))
    return alpha, beta


def _linear(df: pd.DataFrame, beta: dict) -> np.ndarray:
    return sum(df[c].to_numpy(float) * beta.get(c, 0.0)
               for c in FEATURES + ["cp"] if c in df and beta.get(c, 0.0))  + np.zeros(len(df))


def _map_u(groups, sigma2: float, u0: np.ndarray | None = None):
    """Newton MAP of each senator's deviation under a N(0, sigma2) prior."""
    u = np.zeros(len(groups)) if u0 is None else u0.copy()
    se = np.ones(len(groups))
    for k, (_, e0, q, w) in enumerate(groups):
        uk = u[k]
        for _ in range(25):
            z = q * (e0 + uk)
            lam = np.exp(norm.logpdf(z) - log_ndtr(z))
            g = (w * q * lam).sum() - uk / sigma2
            h = -(w * lam * (z + lam)).sum() - 1 / sigma2
            step = g / h
            uk -= step
            if abs(step) < 1e-8:
                break
        u[k], se[k] = uk, 1 / np.sqrt(-h)
    return u, se


# Prior SD used only to decide whether a senator is clearly off the mapping.
# Wide, so a lone deviant is not shrunk out of sight by everyone else's fit.
FLAG_PRIOR_SD = 3.0


def _senator_deviations(df: pd.DataFrame, eta0: np.ndarray, iters: int = 30):
    """Laplace-EM estimate of each senator's deviation u_i and the spread sigma.

    u_latent is shrunk by the fitted sigma (what the model believes);
    u_raw_latent uses a wide prior and is what override suggestions are based on.
    """
    df = df.assign(_eta0=eta0, _q=2 * df["y"] - 1)
    groups = [(bid, g["_eta0"].to_numpy(), g["_q"].to_numpy(), g["w"].to_numpy())
              for bid, g in df.groupby("bioguide_id")]
    sigma2, u = 1.0, None
    for _ in range(iters):
        u, se = _map_u(groups, sigma2, u)
        sigma2 = max(float(np.mean(u ** 2 + se ** 2)), 0.05 ** 2)
    u, se = _map_u(groups, sigma2, u)
    u_raw, se_raw = _map_u(groups, FLAG_PRIOR_SD ** 2)
    out = pd.DataFrame({
        "bioguide_id": [g[0] for g in groups],
        "n_votes": [len(g[1]) for g in groups],
        "u_latent": u,
        "se_latent": se,
        "u_raw_latent": u_raw,
        "se_raw_latent": se_raw,
    })
    return out, float(np.sqrt(sigma2))


def _cv_by_family(df: pd.DataFrame, use_gamma: bool) -> dict:
    """Leave-one-family-out: refit the mapping without a family, then fit only the
    held-out items' cutpoints and score log-loss and within-party accuracy."""
    families = df["family"].unique()
    if len(families) < 2:
        return {}
    losses, correct, total = [], 0, 0
    for fam in families:
        train, test = df[df["family"] != fam], df[df["family"] == fam].copy()
        _, beta = _fit_pooled(train, use_gamma and train["cp"].nunique() > 1)
        test["lin"] = _linear(test, beta)
        for _, g in test.groupby("item_id"):
            y, lin, w = g["y"].to_numpy(), g["lin"].to_numpy(), g["w"].to_numpy()
            res = minimize(lambda a: -(log_ndtr((2 * y - 1) * (a[0] + lin))).sum(), [0.0])
            p = norm.cdf(res.x[0] + lin).clip(1e-6, 1 - 1e-6)
            losses.append(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())
            # Within-party accuracy: party alone cannot inflate it.
            for _, gp in g.assign(p=p).groupby("party"):
                if gp["y"].nunique() > 1:
                    correct += int(((gp["p"] > 0.5) == (gp["y"] == 1)).sum())
                    total += len(gp)
    return {
        "logloss": round(float(np.mean(losses)), 4),
        "within_party_accuracy": round(correct / total, 4) if total else None,
        "within_party_votes": total,
    }


def fit_dimension(df: pd.DataFrame, dimension: str, roster_ideology: pd.DataFrame) -> DimensionFit:
    df = df[df["dimension"] == dimension].copy()
    df, shares = drop_lopsided(df)
    if df.empty:
        raise ValueError(f"No informative items left for {dimension}.")
    fam_size = df.groupby("family")["item_id"].transform("nunique")
    df["w"] = 1 / np.sqrt(fam_size)

    use_gamma = df.groupby("item_id")["president_party"].first().nunique() > 1
    alpha, beta = _fit_pooled(df, use_gamma)
    gamma = float(beta.pop("cp", 0.0))

    eta0 = df["item_id"].map(alpha).to_numpy() + _linear(df, {**beta, "cp": gamma})
    deviations, sigma = _senator_deviations(df, eta0)

    # Scale: mean and SD of the ideology-only latent value across the roster.
    r = roster_ideology.dropna(subset=["d1"]).copy()
    r["d1_sq"] = r["d1"] ** 2
    lin = _linear(r, beta)
    mean, sd = float(lin.mean()), float(lin.std()) or 1.0

    for col in ("u", "se", "u_raw", "se_raw"):
        deviations[f"{col}_score"] = SCORE_K * deviations[f"{col}_latent"] / sd
    deviations["suggest_override"] = (
        (deviations["u_raw_score"].abs() > 2 * deviations["se_raw_score"])
        & (deviations["u_raw_score"].abs() > SUGGEST_OVERRIDE_MIN)
    )

    item_meta = (
        df.groupby("item_id")
        .agg(family=("family", "first"), president_party=("president_party", "first"),
             n=("y", "size"), weight=("w", "first"))
        .reset_index()
    )
    item_meta["alpha"] = item_meta["item_id"].map(alpha)
    item_meta = item_meta.merge(shares, on="item_id", how="left")

    return DimensionFit(
        dimension=dimension,
        beta={k: float(v) for k, v in beta.items()},
        gamma=gamma,
        gamma_identified=bool(use_gamma),
        items=item_meta,
        sigma_latent=sigma,
        scale_mean=mean,
        scale_sd=sd,
        deviations=deviations.assign(dimension=dimension),
        cv=_cv_by_family(df, use_gamma),
    )


def latent_to_score(d1, d2, fit: dict) -> np.ndarray:
    """Apply a stored fit to ideology points: the replacement for a hand formula."""
    b = fit["beta"]
    lin = b.get("d1", 0) * d1 + b.get("d1_sq", 0) * d1 ** 2 + b.get("d2", 0) * d2
    s = fit["scale"]
    return s["k"] * (lin - s["mean"]) / s["sd"]


def save(fits: list[DimensionFit], path: Path, meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, "dimensions": {f.dimension: f.to_dict() for f in fits}}
    path.write_text(json.dumps(payload, indent=2, default=float))


def load(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text()).get("dimensions", {})
