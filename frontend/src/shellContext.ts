import { createContext, useContext } from 'react'

export interface ShellState {
  historyOpen: boolean
  toggleHistory: () => void
}

export const ShellContext = createContext<ShellState>({ historyOpen: false, toggleHistory: () => {} })

export function useShell(): ShellState {
  return useContext(ShellContext)
}
