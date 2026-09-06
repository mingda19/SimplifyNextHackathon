import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useAuth } from '@/lib/use-auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { Building2 } from 'lucide-react'
import { toast } from 'sonner' // <-- Import toast

export const Route = createFileRoute('/signup')({
  component: SignupPage,
})

const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function SignupPage() {
  const { signup } = useAuth()
  const navigate = useNavigate()
  
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)
    
    try {
      await signup(email, password, displayName)
      toast.success("Account created successfully!")
      navigate({ to: '/dashboard' })
    } catch (err: any) {
      // Fire the capitalized error toast
      const errorMessage = err.message || 'Failed to create account.'
      toast.error(capitalize(errorMessage))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen w-full items-center justify-center bg-stone-50/50 p-4">
      <Card className="w-full max-w-md shadow-sm border-stone-200">
        <CardHeader className="space-y-3 text-center pb-6">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10">
            <Building2 className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <CardTitle className="text-2xl font-bold tracking-tight">Create an account</CardTitle>
            <CardDescription className="text-stone-500 text-base">
              Register your charity to start issuing recipient requests.
            </CardDescription>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSignup} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="orgName">Organization Name</Label>
              <Input 
                id="orgName" 
                placeholder="e.g. City Food Bank" 
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required 
                className="bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">Work Email</Label>
              <Input 
                id="email" 
                type="email" 
                placeholder="hello@charity.org" 
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required 
                className="bg-white"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">Password</Label>
              <Input 
                id="password" 
                type="password" 
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required 
                className="bg-white"
              />
              <p className="text-[0.8rem] text-stone-500">
                Must be at least 10 characters with numbers and letters.
              </p>
            </div>
            
            <Button type="submit" className="w-full text-base h-11" disabled={isLoading}>
              {isLoading ? "Creating account..." : "Create Account"}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="flex justify-center border-t border-stone-100 pt-6">
          <p className="text-sm text-stone-500">
            Already have an account?{' '}
            <Link to="/login" className="font-semibold text-primary hover:underline">
              Sign in here
            </Link>
          </p>
        </CardFooter>
      </Card>
    </div>
  )
}