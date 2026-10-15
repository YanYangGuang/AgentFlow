<script setup lang="ts">
withDefaults(defineProps<{ enabled?: boolean; duration?: number; delay?: number }>(), {
  enabled: true,
  duration: 8.2,
  delay: 0,
})
</script>

<template>
  <span class="floating-content" :class="{ 'motion-enabled': enabled }" :style="{ '--float-duration': `${duration}s`, '--float-delay': `${delay}s` }"><slot /></span>
</template>

<style scoped>
.floating-content { display:inline-flex; align-items:center; transition:transform 220ms ease,filter 220ms ease; }
.floating-content.motion-enabled { animation:float-gently var(--float-duration) ease-in-out var(--float-delay) infinite; }
.floating-content:hover { transform:translateY(-2px); filter:drop-shadow(0 3px 7px rgba(82,103,245,.12)); }
@keyframes float-gently { 0%,100% { translate:0 0; } 50% { translate:0 -5px; } }
@media(prefers-reduced-motion:reduce) { .floating-content,.floating-content.motion-enabled { animation:none!important; transition:none!important; translate:none!important; transform:none!important; filter:none!important; } }
</style>
