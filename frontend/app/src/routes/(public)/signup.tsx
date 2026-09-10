import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardDescription, CardHeader, CardTitle, CardFooter } from '@/components/ui/card'
import { Building2 } from 'lucide-react'
import { toast } from 'sonner'
import { PasswordRules } from '@/components/password-rules'
import { usePasswordPolicy } from '@/hooks/use-password-policy'
import { allRulesMet } from '@/lib/password'

export const Route = createFileRoute('/(public)/signup')({
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
  const rules = usePasswordPolicy()
  const canSubmit = allRulesMet(rules, password)

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault()
    setIsLoading(true)

    try {
      const user = await signup(email, password, displayName)
      toast.success("Account created successfully!")
      navigate({ to: user.role === 'charity' ? '/stock' : '/request', replace: true })
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to create account.'
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
            <Building2 className="h-6 w-6 text-primary" />
          </div>
          <div className="space-y-1">
            <CardTitle className="text-2xl font-bold tracking-tight">Create an account</CardTitle>
            <CardDescription className="text-muted-foreground text-base">
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
               
              />
              <PasswordRules rules={rules} password={password} />
            </div>

            <Button
              type="submit"
              className="w-full text-base h-11"
              disabled={isLoading || !canSubmit}
            >
              {isLoading ? "Creating account..." : "Create Account"}
            </Button>
          </form>
        </CardContent>
        <CardFooter className="flex justify-center border-t border-border pt-6">
          <p className="text-sm text-muted-foreground">
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