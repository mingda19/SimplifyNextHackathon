import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { HeartHandshake } from 'lucide-react'
import { toast } from 'sonner' // <-- Import toast

export const Route = createFileRoute('/login')({
  component: LoginPage,
})

// Helper to capitalize the first letter
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    try {
      const user = await login(email, password)
      toast.success("Welcome back!")
      // Route by role: charity staff run operations, everyone else files requests.
      navigate({ to: user.role === 'charity' ? '/stock' : '/request', replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Incorrect email or password.'
      toast.error(capitalize(message))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-muted/40 p-4">
      <Card className="w-full max-w-md shadow-sm">
        <CardHeader className="space-y-3 text-center pb-6">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <HeartHandshake className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <CardTitle className="text-2xl font-bold tracking-tight">Welcome back</CardTitle>
            <CardDescription className="text-muted-foreground text-base">
              Enter your credentials to access your charity dashboard.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleLogin} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="email">Email address</Label>
              <Input 
                id="email" 
                type="email" 
                placeholder="hello@charity.org" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required 
               
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
              </div>
              <Input 
                id="password" 
                type="password" 
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required 
               
              />
            </div>
            
            <Button type="submit" className="w-full text-base h-11" disabled={isLoading}>
              {isLoading ? "Signing in..." : "Sign in"}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="flex justify-center border-t border-border pt-6">
          <p className="text-sm text-muted-foreground">
            Don't have an account?{' '}
            <Link to="/signup" className="font-semibold text-primary hover:underline">
              Register your charity
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  )
}