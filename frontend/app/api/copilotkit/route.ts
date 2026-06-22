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
const AGUI_URL = process.env.AGUI_URL ?? 'http://127.0.0.1:8000/agui?mode=crew'

const copilotRuntime = new CopilotRuntime({
  agents: { tripweaver: new HttpAgent({ url: AGUI_URL }) },
  // Our AG-UI agent already produces the text/tool/A2UI stream, so no LLM
  // service adapter is needed — the empty adapter is the documented choice.
  a2ui: {}, // enable CopilotKit's native A2UI rendering
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
