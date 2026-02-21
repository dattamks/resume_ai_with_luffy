// Decoupled sign-out bridge between api/client.js and AuthContext
// Avoids circular imports while letting the API layer trigger a global sign-out.
let _handler = null

export const setSignOutHandler = (fn) => {
  _handler = fn
}

export const triggerSignOut = () => {
  if (_handler) _handler()
}
