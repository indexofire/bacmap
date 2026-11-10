/// <reference types="vite/client" />

interface Window {
  /** DSH reverse-proxy mount prefix (e.g. "/bacmap"); absent on the native web UI. */
  __BACMAP_MOUNT__?: string
  /** Vue Router base; DSH sets "/bacmap/console/", native web uses "/console/". */
  __BACMAP_ROUTER_BASE__?: string
}
