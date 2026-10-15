<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const root = ref<HTMLElement | null>(null)
let pointerEnabled = false
let pointerQuery: MediaQueryList | undefined
let reducedMotionQuery: MediaQueryList | undefined

function moveWithPointer(event: PointerEvent) {
  if (!pointerEnabled || !root.value) return
  const bounds = root.value.getBoundingClientRect()
  if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) { resetPointer(); return }
  const dx = (event.clientX - (bounds.left + bounds.width / 2)) / Math.max(bounds.width / 2, 1)
  const dy = (event.clientY - (bounds.top + bounds.height / 2)) / Math.max(bounds.height / 2, 1)
  root.value.style.setProperty('--ambient-far-x', `${Math.max(-2, Math.min(2, dx * 2))}px`)
  root.value.style.setProperty('--ambient-far-y', `${Math.max(-2, Math.min(2, dy * 2))}px`)
  root.value.style.setProperty('--ambient-near-x', `${Math.max(-5, Math.min(5, dx * 5))}px`)
  root.value.style.setProperty('--ambient-near-y', `${Math.max(-5, Math.min(5, dy * 5))}px`)
}

function updatePointerCapability() {
  pointerEnabled = Boolean(pointerQuery?.matches && !reducedMotionQuery?.matches)
  if (!pointerEnabled) resetPointer()
}

function resetPointer() {
  if (!root.value) return
  root.value.style.setProperty('--ambient-far-x', '0px')
  root.value.style.setProperty('--ambient-far-y', '0px')
  root.value.style.setProperty('--ambient-near-x', '0px')
  root.value.style.setProperty('--ambient-near-y', '0px')
}

onMounted(() => {
  pointerQuery = window.matchMedia('(pointer: fine)')
  reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
  updatePointerCapability()
  window.addEventListener('pointermove', moveWithPointer, { passive: true })
  pointerQuery.addEventListener('change', updatePointerCapability)
  reducedMotionQuery.addEventListener('change', updatePointerCapability)
})
onBeforeUnmount(() => {
  window.removeEventListener('pointermove', moveWithPointer)
  pointerQuery?.removeEventListener('change', updatePointerCapability)
  reducedMotionQuery?.removeEventListener('change', updatePointerCapability)
})
</script>

<template>
  <div ref="root" class="ambient-motion-bg" aria-hidden="true" @pointerleave="resetPointer">
    <div class="ambient-glow ambient-glow-blue" />
    <div class="ambient-glow ambient-glow-cyan" />
    <div class="ambient-glow ambient-glow-lilac" />
    <svg class="ambient-flow-lines" viewBox="0 0 1440 360" preserveAspectRatio="none">
      <defs>
        <linearGradient id="ambient-flow-gradient" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stop-color="#5267F5" stop-opacity="0" />
          <stop offset=".42" stop-color="#5267F5" stop-opacity=".25" />
          <stop offset=".72" stop-color="#45B8C8" stop-opacity=".22" />
          <stop offset="1" stop-color="#9B8BE8" stop-opacity="0" />
        </linearGradient>
      </defs>
      <path d="M-40 266 C210 140 352 326 590 218 S1012 110 1480 206" />
      <path d="M-30 310 C260 210 388 344 670 260 S1080 164 1460 272" />
    </svg>
    <span class="ambient-orb ambient-orb-one" />
    <span class="ambient-orb ambient-orb-two" />
  </div>
</template>

<style scoped>
.ambient-motion-bg { position:absolute; z-index:0; inset:-24px -28px auto; height:390px; overflow:hidden; pointer-events:none; contain:paint; --ambient-far-x:0px; --ambient-far-y:0px; --ambient-near-x:0px; --ambient-near-y:0px; }
.ambient-glow { position:absolute; border-radius:50%; opacity:.55; will-change:transform; }
.ambient-glow-blue { width:390px; height:250px; top:-125px; left:8%; background:radial-gradient(ellipse,rgba(82,103,245,.14),rgba(82,103,245,0) 70%); filter:blur(18px); transform:translate3d(var(--ambient-far-x),var(--ambient-far-y),0); animation:glow-drift 27s ease-in-out infinite alternate; }
.ambient-glow-cyan { width:340px; height:220px; top:20px; right:16%; background:radial-gradient(ellipse,rgba(69,184,200,.12),rgba(69,184,200,0) 70%); filter:blur(20px); transform:translate3d(var(--ambient-near-x),var(--ambient-near-y),0); animation:glow-drift 23s ease-in-out -9s infinite alternate-reverse; }
.ambient-glow-lilac { width:300px; height:190px; top:70px; right:-5%; background:radial-gradient(ellipse,rgba(155,139,232,.11),rgba(155,139,232,0) 70%); filter:blur(22px); transform:translate3d(var(--ambient-far-x),var(--ambient-far-y),0); animation:glow-drift 30s ease-in-out -14s infinite alternate; }
.ambient-flow-lines { position:absolute; inset:0; width:100%; height:100%; opacity:.56; }
.ambient-flow-lines path { fill:none; stroke:url(#ambient-flow-gradient); stroke-width:1; stroke-dasharray:7 12; animation:flow-dash 32s linear infinite; }
.ambient-flow-lines path+path { opacity:.62; animation-duration:38s; animation-direction:reverse; }
.ambient-orb { position:absolute; width:4px; height:4px; border-radius:50%; background:#7f91f8; opacity:.28; box-shadow:0 0 12px rgba(82,103,245,.3); }
.ambient-orb-one { left:27%; top:44%; }.ambient-orb-two { right:23%; top:60%; width:3px; height:3px; background:#4ebac4; }
@keyframes glow-drift { from { translate:0 -5px; } to { translate:0 7px; } }
@keyframes flow-dash { to { stroke-dashoffset:-180; } }
:global(:root[data-theme='dark']) .ambient-glow { opacity:.38; }
@media(max-width:700px) { .ambient-motion-bg { inset:-18px -14px auto; height:300px; } .ambient-glow { filter:blur(28px); } .ambient-flow-lines { opacity:.32; } .ambient-orb-two { display:none; } }
@media(prefers-reduced-motion:reduce) { .ambient-motion-bg * { animation:none!important; transition:none!important; } .ambient-glow { transform:none!important; translate:none!important; } }
</style>
