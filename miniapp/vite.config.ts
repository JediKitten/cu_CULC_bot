import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    // Свой порт: рядом на этой машине живёт киноклуб, он занимает 5173.
    // Без явного номера Vite молча уезжает на соседний, и туннель начинает
    // светить наружу чужой проект.
    port: 5183,
    // Слушаем все интерфейсы: до dev-сервера ходит HTTPS-туннель, а не localhost.
    host: true,
    // Занятый порт — ошибка, а не повод тихо переехать на соседний.
    strictPort: true,
    // Туннель отдаёт случайный домен вида *.trycloudflare.com, заранее его не знаем.
    allowedHosts: true,
    // API проксируем через тот же origin. Иначе телефону пришлось бы ходить
    // на localhost:8000 разработчика — то есть в никуда, — и понадобился бы
    // второй туннель со своими CORS.
    proxy: {
      "/api": { target: "http://localhost:8010", changeOrigin: true },
      "/health": { target: "http://localhost:8010", changeOrigin: true },
    },
  },
});
