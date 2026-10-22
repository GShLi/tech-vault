import { createApp } from 'vue'
import { createPinia } from 'pinia'
import '@arco-design/web-vue/dist/arco.css'

import App from './App.vue'
import router from './router'
import './styles.css'
import './arco-theme.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.mount('#app')
