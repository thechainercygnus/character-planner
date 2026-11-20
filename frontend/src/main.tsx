import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { publicToken } from './api'
import { PublicPage } from './components/PublicPage'
import { TouchTips } from './components/TouchTips'
import './index.css'

// A public page's link (#42) opens that page alone: no sign-in, nothing of the planner.
const token = publicToken()

const queryClient = new QueryClient({
  defaultOptions: {
    // Character data only changes on sync; don't refetch on every window focus.
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {token ? <PublicPage token={token} /> : <App />}
      <TouchTips />
    </QueryClientProvider>
  </StrictMode>,
)
