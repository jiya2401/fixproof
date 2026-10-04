const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export type AboutResponse = {
  name: string
  tagline: string
  status: string
  target_scope: string
  nebius_model: string
  nebius_configured: boolean
  implemented_now: string[]
  next_milestone: string
}

export async function getAbout(): Promise<AboutResponse> {
  const response = await fetch(`${API_BASE}/api/v1/about`)
  if (!response.ok) throw new Error('Backend is unavailable')
  return response.json()
}
