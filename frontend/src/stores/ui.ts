import { defineStore } from 'pinia'

const storedTheme = localStorage.getItem('agentflow-theme')
const prefersDark = typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches
const systemReducedMotion = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

export const useUiStore = defineStore('ui', {
  state: () => ({ theme: (storedTheme || (prefersDark ? 'dark' : 'light')) as 'light' | 'dark', collapsed: false, ambientMotion: !systemReducedMotion && localStorage.getItem('agentflow-motion') !== 'off' }),
  actions: {
    setTheme(theme: 'light' | 'dark') { this.theme = theme; localStorage.setItem('agentflow-theme', theme); document.documentElement.dataset.theme = theme },
    toggleTheme() { this.setTheme(this.theme === 'light' ? 'dark' : 'light') },
    toggleSidebar() { this.collapsed = !this.collapsed },
    toggleMotion() { this.ambientMotion = !this.ambientMotion; localStorage.setItem('agentflow-motion', this.ambientMotion ? 'on' : 'off'); document.documentElement.dataset.motion = this.ambientMotion ? 'on' : 'off' },
    initialize() { document.documentElement.dataset.theme = this.theme; document.documentElement.dataset.motion = this.ambientMotion ? 'on' : 'off' },
  },
})
