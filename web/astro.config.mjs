import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://yort-feng.github.io',
  base: '/douyin-remix-catalog',
  build: {
    inlineStylesheets: 'auto',
  },
  vite: {
    build: {
      assetsInlineLimit: 0,
    },
  },
});
