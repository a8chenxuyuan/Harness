/** 应用入口：装配 Pinia / Router 并挂载。 */
import { createPinia } from "pinia";
import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import "./styles/global.css";

createApp(App).use(createPinia()).use(router).mount("#app");
