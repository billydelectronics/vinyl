// frontend/tailwind.config.cjs
const { skeleton } = require('@skeletonlabs/tw-plugin');

/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class', // <- important (capital M)
  content: ['./src/**/*.{html,js,svelte,ts}'],
  theme: { extend: {} },
  plugins: [
    require('@tailwindcss/forms'),
    skeleton()
  ]
};
