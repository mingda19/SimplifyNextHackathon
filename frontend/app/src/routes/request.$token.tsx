// src/routes/request.$token.tsx
import { createFileRoute } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import { client, feedbackClient } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { toast } from 'sonner'
import { CheckCircle2, HeartHandshake } from 'lucide-react'

export const Route = createFileRoute('/request/$token')({
  component: RequestIntakePage,
})

function RequestIntakePage() {
  // Grab the token directly from the URL!
  const { token } = Route.useParams()
  
  const [isValidating, setIsValidating] = useState(true)
  const [charityName, setCharityName] = useState("")
  const [error, setError] = useState(false)
  
  const [feedback, setFeedback] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSuccess, setIsSuccess] = useState(false)

  // 1. Validate the token when the page loads
  useEffect(() => {
    const validateToken = async () => {
      const { data, error } = await client.GET("/auth/request-links/{token}", {
        params: { path: { token } }
      })

      if (error || !data) {
        setError(true)
      } else {
        // Assuming your backend returns a 'charity_name' field as per your Python SQL JOIN
        setCharityName((data as any).charity_name || "the charity")
      }
      setIsValidating(false)
    }
    validateToken()
  }, [token])

  // 2. Submit the request
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!feedback.trim()) return

    setIsSubmitting(true)
    
    // Step A: Send the text to the Feedback Microservice
    const { error: submitError } = await feedbackClient.POST("/feedback", {
      body: {
        beneficiary_id: `ANON-${token.slice(0, 4)}`, // Temp ID for anonymous link users
        text: feedback,
        lang: "en",
        channel: "web"
      }
    })

    if (submitError) {
      toast.error("Something went wrong. Please try again.")
      setIsSubmitting(false)
      return
    }

    // Step B: Mark the token as used in the Auth Microservice
    await client.POST("/auth/request-links/{token}/used", {
      params: { path: { token } }
    })

    setIsSuccess(true)
    setIsSubmitting(false)
  }

  // --- RENDERING STATES ---

  if (isValidating) {
    return <div className="flex min-h-screen items-center justify-center bg-muted/40"><p className="text-xl animate-pulse text-muted-foreground">Loading...</p></div>
  }

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
        <Card className="w-full max-w-md text-center shadow-sm">
          <CardHeader>
            <CardTitle className="text-xl text-destructive">Link Invalid or Expired</CardTitle>
            <CardDescription className="text-base text-muted-foreground">
              This request link is no longer valid. Please contact your charity organizer for a new one.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  if (isSuccess) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40 p-4">
        <Card className="w-full max-w-md text-center border-emerald-200 shadow-sm">
          <CardHeader className="space-y-4">
            <CheckCircle2 className="w-16 h-16 text-emerald-500 mx-auto" />
            <CardTitle className="text-2xl text-foreground">Request Sent!</CardTitle>
            <CardDescription className="text-lg text-muted-foreground">
              We have received your message and sent it directly to {charityName}. They will review your needs shortly.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-muted/40 p-4">
      <div className="mb-6 flex flex-col items-center text-center">
        <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary/10">
          <HeartHandshake className="h-8 w-8 text-primary" />
        </div>
        <h1 className="text-2xl font-bold text-foreground tracking-tight mb-1">
          {charityName} Request Form
        </h1>
        <p className="text-muted-foreground max-w-sm">
          Tell us what you need this week. No password required.
        </p>
      </div>

      <Card className="w-full max-w-md shadow-sm">
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-3">
              <label htmlFor="feedback" className="text-lg font-medium text-foreground leading-tight block">
                What items do you and your family need most right now?
              </label>
              <Textarea 
                id="feedback" 
                placeholder="e.g., 'We need baby formula and diapers size 4. Also running low on rice.'" 
                className="min-h-[150px] text-lg p-4 resize-none"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
                required 
              />
            </div>
            
            <Button 
              type="submit" 
              className="w-full h-14 text-lg font-medium shadow-sm" 
              disabled={isSubmitting}
            >
              {isSubmitting ? "Sending..." : "Submit Request"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}