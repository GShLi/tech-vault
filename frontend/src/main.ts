import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Drawer, Modal, Spin, Tag } from '@arco-design/web-vue'
import '@arco-design/web-vue/dist/arco.css'

import App from './App.vue'
import router from './router'
import './styles.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.component('AModal', Modal)
app.component('ASpin', Spin)
app.component('ATag', Tag)
app.component('ADrawer', Drawer)
app.mount('#app')
