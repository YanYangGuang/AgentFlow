import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import App from './App.vue'
import router from './router'
import './styles/tokens.css'
import './styles/readability.css'

createApp(App).use(createPinia()).use(router).use(ElementPlus, { size: 'default' }).mount('#app')
