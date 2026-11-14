import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'
import { TouchTips } from './components/TouchTips'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    // Character data only changes on sync; don't refetch on every window focus.
    queries: { refetchOnWindowFocus: false, retry: 1 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <TouchTips />
    </QueryClientProvider>
  </StrictMode>,
)
