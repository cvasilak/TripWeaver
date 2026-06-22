import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'TripWeaver — CopilotKit',
  description: 'CopilotKit (full runtime) frontend for the TripWeaver AG-UI agent',
}

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
