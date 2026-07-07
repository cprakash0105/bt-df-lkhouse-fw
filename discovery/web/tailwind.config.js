/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        ontika: {
          blue: '#4F46E5',
          purple: '#7C3AED',
          gold: '#F59E0B',
          navy: '#1E1B4B',
          light: '#F8FAFC',
          card: '#FFFFFF',
        },
      },
      boxShadow: {
        'card': '0 2px 8px rgba(0, 0, 0, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04)',
        'card-hover': '0 8px 24px rgba(79, 70, 229, 0.12), 0 4px 12px rgba(0, 0, 0, 0.06)',
        'elevated': '0 12px 40px rgba(0, 0, 0, 0.08), 0 4px 12px rgba(0, 0, 0, 0.04)',
        'chat': '0 -2px 12px rgba(0, 0, 0, 0.04)',
      },
    },
  },
  plugins: [],
}
