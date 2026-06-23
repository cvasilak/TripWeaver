'use client'

import { useEffect } from 'react'
import { CopilotKit, useCopilotAction } from '@copilotkit/react-core'
import { CopilotChat } from '@copilotkit/react-ui'
import '@copilotkit/react-ui/styles.css'
import { A2UIProvider, A2UIRenderer, useA2UI, basicCatalog } from '@copilotkit/a2ui-renderer'

const CATALOG_ID = 'https://a2ui.org/specification/v0_9/basic_catalog.json'

// Renders one A2UI surface from a render_a2ui tool call's args. The agent sends
// {surfaceId, components, data}; we feed the equivalent v0.9 messages into the
// A2UI store and render the surface.
function A2UISurface({ surfaceId, components, data }: { surfaceId?: string; components?: unknown; data?: unknown }) {
  const { processMessages } = useA2UI()
  const ready = !!surfaceId && Array.isArray(components) && components.length > 0
  useEffect(() => {
    if (!ready) return
    const messages: Array<Record<string, unknown>> = [
      { version: 'v0.9', createSurface: { surfaceId, catalogId: CATALOG_ID } },
      { version: 'v0.9', updateComponents: { surfaceId, components } },
    ]
    if (data && typeof data === 'object' && Object.keys(data as object).length) {
      messages.push({ version: 'v0.9', updateDataModel: { surfaceId, path: '/', value: data } })
    }
    processMessages(messages)
  }, [ready, surfaceId, components, data, processMessages])
  // Wrap in .tw-a2ui so we can give the surface a consistent light "card panel"
  // look — its components render white cards + transparent areas with inherited
  // (light) text, which is invisible on the dark chat. See globals.css.
  return ready ? (
    <div className="tw-a2ui">
      <A2UIRenderer surfaceId={surfaceId as string} />
    </div>
  ) : null
}

// Register the render_a2ui tool so its calls render as A2UI surfaces (generative
// UI) instead of a generic tool card. The runtime's a2ui middleware is disabled,
// so the tool call reaches us here.
function RegisterA2UIRenderer() {
  useCopilotAction({
    name: 'render_a2ui',
    // available:"disabled" => a render-only action: not advertised as callable,
    // but its incoming tool calls are rendered (CopilotKit's generative UI).
    available: 'disabled',
    render: ({ args }) => (
      <A2UISurface
        surfaceId={(args as Record<string, unknown>)?.surfaceId as string}
        components={(args as Record<string, unknown>)?.components}
        data={(args as Record<string, unknown>)?.data}
      />
    ),
  })
  return null
}

export default function Home() {
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" agent="tripweaver">
      <A2UIProvider catalog={basicCatalog} onAction={(a: unknown) => console.log('[a2ui action]', a)}>
        <div className="shell">
          <header>
            <h1>TripWeaver — CopilotKit (full runtime)</h1>
            <p>
              The CopilotKit runtime drives our AG-UI agent; A2UI surfaces render in the chat.
              Try: <em>“Plan my 8-day trip to Tokyo.”</em>
            </p>
          </header>
          <RegisterA2UIRenderer />
          <div className="chat">
            <CopilotChat
              labels={{
                title: 'TripWeaver',
                initial: 'Hi! Ask me to plan a trip — e.g. “Plan my 8-day Tokyo trip”.',
              }}
            />
          </div>
        </div>
      </A2UIProvider>
    </CopilotKit>
  )
}
