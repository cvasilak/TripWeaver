'use client'

import { useEffect, useState } from 'react'
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

// Render-only: while a crew agent is running, the backend emits an in-progress
// `agent_step` tool call; show it as "Starting <Agent>…" with a spinner, then a
// done marker when it completes.
function RegisterAgentStep() {
  useCopilotAction({
    name: 'agent_step',
    available: 'disabled',
    render: ({ status, args }) => {
      const agent = ((args as Record<string, unknown>)?.agent as string) || 'agent'
      const done = status === 'complete'
      return (
        <div className="tw-agent-step">
          <span className={done ? 'tw-dot-done' : 'tw-spinner'} aria-hidden />
          <span>{done ? `${agent} — done` : `Starting ${agent}…`}</span>
        </div>
      )
    },
  })
  return null
}

type FlightOption = {
  ref?: string
  airline?: string
  stops?: number
  duration_hours?: number
  price_per_person?: number
  why?: string
}
type HotelOption = {
  ref?: string
  name?: string
  area?: string
  price_per_night?: number
  why?: string
}

// The human-in-the-loop picker. The backend's research crew hands us ranked
// flight + hotel options via a `select_options` tool call and waits; the traveler
// picks one of each and we send the chosen objects back via respond(). The crew's
// planning phase then builds the itinerary around that choice (a follow-up run).
function SelectOptions({
  flights,
  hotels,
  status,
  respond,
}: {
  flights: FlightOption[]
  hotels: HotelOption[]
  status: string
  respond?: (result: unknown) => void
}) {
  const [flightRef, setFlightRef] = useState<string | null>(null)
  const [hotelRef, setHotelRef] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState<{ flight?: FlightOption; hotel?: HotelOption } | null>(null)

  const keyOf = (o: FlightOption | HotelOption, i: number) => o.ref ?? String(i)
  const chosenFlight = flights.find((f, i) => keyOf(f, i) === flightRef)
  const chosenHotel = hotels.find((h, i) => keyOf(h, i) === hotelRef)
  const canSubmit = status === 'executing' && !!chosenFlight && !!chosenHotel && !!respond

  // After respond(), the action re-renders as "complete"; show what was booked-in.
  if (status === 'complete' || submitted) {
    const f = submitted?.flight ?? chosenFlight
    const h = submitted?.hotel ?? chosenHotel
    return (
      <div className="tw-pick tw-pick-done">
        <span className="tw-dot-done" aria-hidden />
        <span>
          Selected{f ? ` ${f.airline}` : ''}
          {h ? ` · ${h.name}` : ''} — planning your itinerary…
        </span>
      </div>
    )
  }

  if (!flights.length && !hotels.length) {
    return (
      <div className="tw-pick">
        <div className="tw-agent-step">
          <span className="tw-spinner" aria-hidden />
          <span>Gathering your options…</span>
        </div>
      </div>
    )
  }

  const submit = () => {
    if (!canSubmit) return
    setSubmitted({ flight: chosenFlight, hotel: chosenHotel })
    respond?.({ flight: chosenFlight, hotel: chosenHotel })
  }

  return (
    <div className="tw-pick">
      <h3 className="tw-pick-title">Choose your flight</h3>
      <div className="tw-opts">
        {flights.map((f, i) => {
          const k = keyOf(f, i)
          return (
            <button
              type="button"
              key={k}
              className={`tw-opt${flightRef === k ? ' tw-opt-sel' : ''}`}
              onClick={() => setFlightRef(k)}
              aria-pressed={flightRef === k}
            >
              <span className="tw-radio" aria-hidden />
              <span className="tw-opt-body">
                <span className="tw-opt-head">
                  <span className="tw-opt-name">{f.airline ?? 'Flight'}</span>
                  {f.price_per_person != null && (
                    <span className="tw-opt-price">{f.price_per_person} /pp</span>
                  )}
                </span>
                <span className="tw-opt-meta">
                  {[
                    f.stops != null ? (f.stops === 0 ? 'nonstop' : `${f.stops} stop${f.stops > 1 ? 's' : ''}`) : null,
                    f.duration_hours != null ? `${f.duration_hours}h` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
                {f.why && <span className="tw-opt-why">{f.why}</span>}
              </span>
            </button>
          )
        })}
      </div>

      <h3 className="tw-pick-title">Choose your hotel</h3>
      <div className="tw-opts">
        {hotels.map((h, i) => {
          const k = keyOf(h, i)
          return (
            <button
              type="button"
              key={k}
              className={`tw-opt${hotelRef === k ? ' tw-opt-sel' : ''}`}
              onClick={() => setHotelRef(k)}
              aria-pressed={hotelRef === k}
            >
              <span className="tw-radio" aria-hidden />
              <span className="tw-opt-body">
                <span className="tw-opt-head">
                  <span className="tw-opt-name">{h.name ?? 'Hotel'}</span>
                  {h.price_per_night != null && (
                    <span className="tw-opt-price">{h.price_per_night} /night</span>
                  )}
                </span>
                <span className="tw-opt-meta">{h.area ?? ''}</span>
                {h.why && <span className="tw-opt-why">{h.why}</span>}
              </span>
            </button>
          )
        })}
      </div>

      <button type="button" className="tw-pick-go" onClick={submit} disabled={!canSubmit}>
        {chosenFlight && chosenHotel ? 'Plan my trip with these' : 'Pick a flight and a hotel'}
      </button>
    </div>
  )
}

// Register the select_options tool as a human-in-the-loop action: it renders the
// picker and waits for the traveler's response (respond), which the agent reads
// on its next run.
function RegisterSelectOptions() {
  useCopilotAction({
    name: 'select_options',
    available: 'disabled',
    renderAndWaitForResponse: ({ status, args, respond }) => {
      const a = (args ?? {}) as { flights?: FlightOption[]; hotels?: HotelOption[] }
      return (
        <SelectOptions
          flights={Array.isArray(a.flights) ? a.flights : []}
          hotels={Array.isArray(a.hotels) ? a.hotels : []}
          status={status}
          respond={respond as ((result: unknown) => void) | undefined}
        />
      )
    },
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
          <RegisterAgentStep />
          <RegisterSelectOptions />
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
