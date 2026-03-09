import { createContext, useContext, useState } from 'react'

const MaskContext = createContext()

export function MaskProvider({ children }) {
  const [maskSettings, setMaskSettings] = useState({
    visible: true,
    opacity: 75,
    blendMode: 'multiply'
  })

  const toggleMask = () => {
    setMaskSettings(prev => ({ ...prev, visible: !prev.visible }))
  }

  const setOpacity = (opacity) => {
    setMaskSettings(prev => ({ ...prev, opacity }))
  }

  const setBlendMode = (blendMode) => {
    setMaskSettings(prev => ({ ...prev, blendMode }))
  }

  return (
    <MaskContext.Provider value={{
      maskSettings,
      toggleMask,
      setOpacity,
      setBlendMode
    }}>
      {children}
    </MaskContext.Provider>
  )
}

export function useMask() {
  const context = useContext(MaskContext)
  if (!context) {
    throw new Error('useMask must be used within MaskProvider')
  }
  return context
}
