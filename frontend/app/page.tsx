'use client'

import { CopilotKit } from '@copilotkit/react-core'
import { CopilotChat } from '@copilotkit/react-ui'
import '@copilotkit/react-ui/styles.css'

export default function Home() {
  return (
    // runtimeUrl points at our Next route; `agent` selects the agent registered
    // in the CopilotRuntime (see app/api/copilotkit/route.ts).
    <CopilotKit runtimeUrl="/api/copilotkit" agent="tripweaver">
      <div className="shell">
        <header>
          <h1>TripWeaver — CopilotKit (full runtime)</h1>
          <p>
            The CopilotKit runtime drives our AG-UI agent; A2UI surfaces render natively in the chat.
            Try: <em>“Plan my 8-day trip to Tokyo.”</em>
          </p>
        </header>
        <div className="chat">
          <CopilotChat
            labels={{
              title: 'TripWeaver',
              initial: 'Hi! Ask me to plan a trip — e.g. “Plan my 8-day Tokyo trip”.',
            }}
          />
        </div>
      </div>
    </CopilotKit>
  )
}
