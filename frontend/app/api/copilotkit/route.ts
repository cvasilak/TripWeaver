// CopilotKit runtime — the "extra Node dependency". It bridges the React app to
// our self-hosted AG-UI agent: the browser talks to /api/copilotkit (same
// origin, no CORS), and this route forwards to the AG-UI server server-to-server
// via @ag-ui/client's HttpAgent.
import {
  CopilotRuntime,
  ExperimentalEmptyAdapter,
  copilotRuntimeNextJSAppRouterEndpoint,
} from '@copilotkit/runtime'
import { HttpAgent } from '@ag-ui/client'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

// The AG-UI server (agui.server). mode=crew makes it emit Crew surfaces, which
// CopilotKit's native A2UI middleware (enabled below) renders in the chat.
// a2ui=tool makes the AG-UI server emit A2UI surfaces as render_a2ui tool calls
// (which we render in app/page.tsx) rather than CUSTOM events. No server env var
// needed — the carrier is requested per-call here.
const AGUI_URL = process.env.AGUI_URL ?? 'http://127.0.0.1:8000/agui?mode=crew&a2ui=tool'

const copilotRuntime = new CopilotRuntime({
  agents: { tripweaver: new HttpAgent({ url: AGUI_URL }) },
  // Our AG-UI agent already produces the text/tool/A2UI stream, so no LLM
  // service adapter is needed — the empty adapter is the documented choice.
  //
  // We deliberately do NOT enable the `a2ui: {}` middleware: it consumes the
  // agent's render_a2ui tool call server-side and renders via react-core's
  // internal path (which doesn't surface through <CopilotChat> in this empty-
  // adapter setup). Instead we let the render_a2ui tool call reach the browser
  // and render it ourselves with useCopilotAction + @copilotkit/a2ui-renderer
  // (see app/page.tsx).
})

const serviceAdapter = new ExperimentalEmptyAdapter()

export const POST = async (req: Request): Promise<Response> => {
  const { handleRequest } = copilotRuntimeNextJSAppRouterEndpoint({
    runtime: copilotRuntime,
    serviceAdapter,
    endpoint: '/api/copilotkit',
  })
  return handleRequest(req)
}
