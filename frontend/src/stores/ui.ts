import { defineStore } from 'pinia'
export const useUiStore = defineStore('ui', {
  state: () => ({ theme: (localStorage.getItem('agentflow-theme') || 'light') as 'light' | 'dark', collapsed: false, ambientMotion: localStorage.getItem('agentflow-motion') !== 'off' }),
  actions: {
    setTheme(theme: 'light' | 'dark') { this.theme = theme; localStorage.setItem('agentflow-theme', theme); document.documentElement.dataset.theme = theme },
    toggleTheme() { this.setTheme(this.theme === 'light' ? 'dark' : 'light') },
    toggleSidebar() { this.collapsed = !this.collapsed },
    toggleMotion() { this.ambientMotion = !this.ambientMotion; localStorage.setItem('agentflow-motion', this.ambientMotion ? 'on' : 'off'); document.documentElement.dataset.motion = this.ambientMotion ? 'on' : 'off' },
  },
})
