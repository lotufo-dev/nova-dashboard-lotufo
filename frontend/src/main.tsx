import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
// depois de index.css de proposito: tokens.css e' o mundo visual e vence as
// regras soltas de la'.
import './tokens.css'
import App from './App.tsx'
import ErrorBoundary from './ErrorBoundary.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
