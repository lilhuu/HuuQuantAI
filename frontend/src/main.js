import { createApp } from "vue";

import App from "./App.vue";
import router from "./router";
import { pinia } from "./stores/pinia";
import { useTradingStore } from "./stores/trading";
import "./styles.css";

const app = createApp(App);

app.use(pinia);
app.use(router);
app.config.errorHandler = (error, _instance, info) => {
  const store = useTradingStore();
  store.setError(error, `界面运行异常：${info || "未知位置"}`);
};
app.mount("#app");
