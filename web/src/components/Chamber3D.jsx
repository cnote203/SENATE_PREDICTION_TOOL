import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { CAUCUS, lastName } from '../util.js'

// The chamber seen from behind the presiding officer's chair: 100 mahogany desks on
// six tiers, each with a lit inlay in the senator's color and a caucus nameplate.

const ROWS = 6
const R0 = 3.3
const R1 = 7.5
const STEP = 0.17 // tier rise
const NAVY = new THREE.Color('#0f1c2e')

function layout(n) {
  const radii = Array.from({ length: ROWS }, (_, i) => R0 + (i * (R1 - R0)) / (ROWS - 1))
  const total = radii.reduce((a, b) => a + b, 0)
  const counts = radii.map((r) => Math.floor((n * r) / total))
  let left = n - counts.reduce((a, b) => a + b, 0)
  for (let i = ROWS - 1; left > 0; i = (i - 1 + ROWS) % ROWS, left--) counts[i]++
  const seats = []
  radii.forEach((r, row) => {
    const k = counts[row]
    for (let j = 0; j < k; j++) {
      const a = Math.PI - (Math.PI * (j + 0.5)) / k
      seats.push({ x: r * Math.cos(a), z: -r * Math.sin(a), y: (row + 1) * STEP, angle: a, row })
    }
  })
  // Same order as the flat plan: left to right, then inner to outer.
  return seats.sort((s, t) => t.angle - s.angle || s.row - t.row)
}

const SEATS = layout(100)

// colorOf may return rgba(); three.js ignores alpha, so blend it over the floor instead.
function toColor(css, out) {
  const m = /^rgba\(([^)]+)\)$/.exec(css || '')
  if (m) {
    const [r, g, b, a] = m[1].split(',').map(Number)
    return out.setRGB(r / 255, g / 255, b / 255, THREE.SRGBColorSpace).lerp(NAVY, 1 - (Number.isFinite(a) ? a : 1))
  }
  return out.setStyle(css || '#3a4454', THREE.SRGBColorSpace)
}

function tierGeometry(rIn, rOut, height) {
  const shape = new THREE.Shape()
  shape.absarc(0, 0, rOut, 0, Math.PI, false)
  shape.absarc(0, 0, rIn, Math.PI, 0, true)
  const g = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false, curveSegments: 72 })
  g.rotateX(-Math.PI / 2) // extrude upward, upper half of the shape goes away from the camera
  return g
}

function arcLine(r, y, material) {
  const pts = []
  for (let i = 0; i <= 96; i++) {
    const a = (Math.PI * i) / 96
    pts.push(new THREE.Vector3(r * Math.cos(a), y, -r * Math.sin(a)))
  }
  return new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), material)
}

export default function Chamber3D({ senators, order, colorOf, selected, onSelect, center }) {
  const mountRef = useRef(null)
  const sceneRef = useRef(null)
  const [hover, setHover] = useState(null) // { id, x, y }
  const byId = useMemo(() => new Map(senators.map((s) => [s.id, s])), [senators])

  // Build the scene once.
  useEffect(() => {
    const mount = mountRef.current
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.shadowMap.enabled = true
    renderer.shadowMap.type = THREE.PCFSoftShadowMap
    renderer.outputColorSpace = THREE.SRGBColorSpace
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.05
    mount.appendChild(renderer.domElement)

    const scene = new THREE.Scene()
    scene.fog = new THREE.Fog(NAVY, 19, 34)
    const camera = new THREE.PerspectiveCamera(28, 2, 0.1, 80)
    const target = new THREE.Vector3(0, 0.2, -3.4)

    // Light: cool skylight from the chamber's glass ceiling, warm key from the press gallery.
    scene.add(new THREE.HemisphereLight('#c9d6ea', '#0f1c2e', 0.85))
    const key = new THREE.DirectionalLight('#ffe7c4', 2.1)
    key.position.set(-4, 11, 6)
    key.castShadow = true
    key.shadow.mapSize.set(2048, 2048)
    Object.assign(key.shadow.camera, { left: -10, right: 10, top: 10, bottom: -10, near: 1, far: 30 })
    key.shadow.bias = -0.0008
    scene.add(key)
    const rim = new THREE.DirectionalLight('#8fb2e8', 0.6)
    rim.position.set(6, 5, -10)
    scene.add(rim)

    const room = new THREE.Group()
    scene.add(room)

    // Floor and tiers in the blue chamber carpet, brass edging on every step.
    const carpet = new THREE.MeshStandardMaterial({ color: '#1a2c47', roughness: 0.95 })
    const floor = new THREE.Mesh(new THREE.CircleGeometry(40, 96), new THREE.MeshStandardMaterial({ color: '#13223a', roughness: 1 }))
    floor.rotation.x = -Math.PI / 2
    floor.receiveShadow = true
    room.add(floor)
    const brass = new THREE.LineBasicMaterial({ color: '#c8a45e', transparent: true, opacity: 0.55 })
    const radii = Array.from({ length: ROWS }, (_, i) => R0 + (i * (R1 - R0)) / (ROWS - 1))
    radii.forEach((r, i) => {
      const half = (R1 - R0) / (ROWS - 1) / 2
      const tier = new THREE.Mesh(tierGeometry(r - half, i === ROWS - 1 ? r + 1.4 : r + half, (i + 1) * STEP), carpet)
      tier.receiveShadow = true
      room.add(tier)
      room.add(arcLine(r - half, (i + 1) * STEP + 0.002, brass))
    })
    // The well: a brass compass ring set into the floor, and the marble rostrum.
    const ring = new THREE.Mesh(new THREE.RingGeometry(R0 - 1.05, R0 - 1.0, 128, 1, 0, Math.PI), new THREE.MeshBasicMaterial({ color: '#c8a45e', side: THREE.DoubleSide }))
    ring.rotation.x = -Math.PI / 2
    ring.position.y = 0.003
    room.add(ring)
    const mahogany = new THREE.MeshStandardMaterial({ color: '#5a2a1e', roughness: 0.42, metalness: 0.05 })
    const marble = new THREE.MeshStandardMaterial({ color: '#9d9583', roughness: 0.35 })
    const rostrum = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.42, 0.5), mahogany)
    rostrum.position.set(0, 0.21, 0.2)
    rostrum.castShadow = true
    room.add(rostrum)
    const rostrumTop = new THREE.Mesh(new THREE.BoxGeometry(1.66, 0.04, 0.56), marble)
    rostrumTop.position.set(0, 0.44, 0.2)
    room.add(rostrumTop)

    // Desks: body, lit inlay (the senator's color) and a caucus nameplate facing the well.
    const deskGeo = new THREE.BoxGeometry(0.6, 0.36, 0.4)
    const inlayGeo = new THREE.BoxGeometry(0.48, 0.03, 0.28)
    const plateGeo = new THREE.BoxGeometry(0.42, 0.07, 0.015)
    const desks = SEATS.map((p) => {
      const g = new THREE.Group()
      g.position.set(p.x, p.y, p.z)
      g.lookAt(0, p.y, 0)
      const body = new THREE.Mesh(deskGeo, mahogany)
      body.position.y = 0.18
      body.castShadow = true
      body.receiveShadow = true
      const inlay = new THREE.Mesh(inlayGeo, new THREE.MeshStandardMaterial({ color: '#3a4454', emissive: '#3a4454', emissiveIntensity: 0.5, roughness: 0.35 }))
      inlay.position.y = 0.375
      const plate = new THREE.Mesh(plateGeo, new THREE.MeshStandardMaterial({ color: '#888', emissive: '#888', emissiveIntensity: 0.6 }))
      plate.position.set(0, 0.27, 0.205)
      g.add(body, inlay, plate)
      g.userData = { seat: p, inlay, plate, base: p.y, lift: 0, liftTarget: 0, rise: reduced ? 1 : 0 }
      room.add(g)
      return g
    })

    // Interaction: drag to turn the room a little, click a desk to open its file.
    const state = { yaw: 0, pitch: 0, yawT: 0, pitchT: 0, drag: null, moved: 0 }
    const ray = new THREE.Raycaster()
    const ndc = new THREE.Vector2()
    const pick = (e) => {
      const r = renderer.domElement.getBoundingClientRect()
      ndc.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      const hit = ray.intersectObjects(desks, true)[0]
      if (!hit) return null
      let o = hit.object
      while (o && !desks.includes(o)) o = o.parent
      return o ? { index: desks.indexOf(o), x: e.clientX - r.left, y: e.clientY - r.top } : null
    }
    const onDown = (e) => { state.drag = { x: e.clientX, y: e.clientY, yaw: state.yawT, pitch: state.pitchT }; state.moved = 0 }
    const onMove = (e) => {
      if (state.drag) {
        const dx = e.clientX - state.drag.x
        const dy = e.clientY - state.drag.y
        state.moved = Math.max(state.moved, Math.abs(dx) + Math.abs(dy))
        state.yawT = THREE.MathUtils.clamp(state.drag.yaw + dx * 0.004, -0.55, 0.55)
        state.pitchT = THREE.MathUtils.clamp(state.drag.pitch + dy * 0.002, -0.12, 0.22)
      }
      const p = state.moved > 4 ? null : pick(e)
      sceneRef.current?.setHover(p)
      renderer.domElement.style.cursor = state.drag && state.moved > 4 ? 'grabbing' : p ? 'pointer' : 'grab'
    }
    const onUp = (e) => {
      if (state.drag && state.moved <= 4) {
        const p = pick(e)
        sceneRef.current?.click(p ? p.index : null)
      }
      state.drag = null
    }
    const onLeave = () => { state.drag = null; sceneRef.current?.setHover(null) }
    const el = renderer.domElement
    el.addEventListener('pointerdown', onDown)
    el.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
    el.addEventListener('pointerleave', onLeave)

    const resize = () => {
      const w = mount.clientWidth
      const h = Math.round(Math.min(w * 0.47, 560))
      renderer.setSize(w, h)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    const ro = new ResizeObserver(resize)
    ro.observe(mount)
    resize()

    // One orchestrated moment: desks rise into place from the far left to the far right.
    const t0 = performance.now()
    let raf
    const tick = (now) => {
      const k = reduced ? 1 : 0.08
      state.yaw += (state.yawT - state.yaw) * k
      state.pitch += (state.pitchT - state.pitch) * k
      const dist = 18.6
      const elev = 0.7 + state.pitch
      camera.position.set(
        target.x + Math.sin(state.yaw) * Math.cos(elev) * dist,
        target.y + Math.sin(elev) * dist,
        target.z + Math.cos(state.yaw) * Math.cos(elev) * dist,
      )
      camera.lookAt(target)
      desks.forEach((d) => {
        const u = d.userData
        if (u.rise < 1) {
          const delay = (Math.PI - u.seat.angle) * 260 + u.seat.row * 60
          const t = THREE.MathUtils.clamp((now - t0 - delay) / 700, 0, 1)
          u.rise = t
        }
        u.lift += (u.liftTarget - u.lift) * (reduced ? 1 : 0.15)
        const ease = 1 - Math.pow(1 - u.rise, 3)
        d.position.y = u.base - (1 - ease) * 0.9 + u.lift
        d.scale.setScalar(0.6 + 0.4 * ease)
      })
      renderer.render(scene, camera)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)

    sceneRef.current = { desks, setHover: () => {}, click: () => {} }
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      el.removeEventListener('pointerdown', onDown)
      el.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      el.removeEventListener('pointerleave', onLeave)
      scene.traverse((o) => {
        o.geometry?.dispose()
        if (o.material) [].concat(o.material).forEach((m) => m.dispose())
      })
      renderer.dispose()
      mount.removeChild(el)
      sceneRef.current = null
    }
  }, [])

  // Paint the desks from props on every render.
  useEffect(() => {
    const sc = sceneRef.current
    if (!sc) return
    const c = new THREE.Color()
    sc.desks.forEach((d, i) => {
      const s = byId.get(order[i])
      const u = d.userData
      u.id = s?.id
      toColor(s ? colorOf(s) : '#1a2230', c)
      u.inlay.material.color.copy(c)
      u.inlay.material.emissive.copy(c)
      u.inlay.material.emissiveIntensity = s?.id === selected ? 1.4 : 0.55
      u.plate.material.color.setStyle(s ? CAUCUS[s.caucus]?.color ?? '#888' : '#333', THREE.SRGBColorSpace)
      u.plate.material.emissive.copy(u.plate.material.color)
      u.liftTarget = s?.id === selected ? 0.32 : 0
    })
    sc.setHover = (p) => setHover(p ? { id: sc.desks[p.index].userData.id, x: p.x, y: p.y } : null)
    sc.click = (index) => {
      const id = index == null ? null : sc.desks[index].userData.id
      onSelect(id && id !== selected ? id : null)
    }
  })

  const hovered = hover && byId.get(hover.id)
  return (
    <div className="chamber3d">
      <div ref={mountRef} className="chamber3d-canvas" role="img" aria-label="Three-dimensional Senate chamber. Each desk is one senator; drag to turn the room, click a desk to open that senator's file." />
      {hovered && (
        <div className="seat-tip" style={{ left: hover.x, top: hover.y }}>
          <b>{lastName(hovered.name)}</b> <span>{hovered.state}, {hovered.caucus === 'D' ? 'Democrat' : 'Republican'}</span>
        </div>
      )}
      <svg className="chamber3d-center" viewBox="0 334 900 106" aria-hidden="true">{center}</svg>
    </div>
  )
}
