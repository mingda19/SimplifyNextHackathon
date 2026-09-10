// src/routes/links.tsx
import { createFileRoute } from '@tanstack/react-router'
import { useState, useEffect } from 'react'
import { client } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Badge } from '@/components/ui/badge'
import { Copy, Trash2, Plus } from 'lucide-react'
import { toast } from 'sonner'

export const Route = createFileRoute('/_app/people')({
  component: LinksPage,
})

// Types based on your Python backend response
type RequestLink = {
  token: string;
  label: string;
  is_active: boolean;
  created_at: string;
  uses: number;
}

function LinksPage() {
  const [links, setLinks] = useState<RequestLink[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const fetchLinks = async () => {
    setIsLoading(true)
    const { data, error } = await client.GET("/auth/request-links")
    if (error) {
      toast.error("Failed to load request links")
    } else {
      setLinks(data as RequestLink[])
    }
    setIsLoading(false)
  }

  useEffect(() => {
    fetchLinks()
  }, [])

  const handleCreateLink = async () => {
    // Note: FastAPI expects 'label' as a query parameter based on your Python code
    const { error } = await client.POST("/auth/request-links", {
      params: { query: { label: "General Intake Link" } }
    })
    
    if (error) {
      toast.error("Failed to create link")
    } else {
      toast.success("New public link generated!")
      fetchLinks()
    }
  }

  const handleRevoke = async (token: string) => {
    const { error } = await client.DELETE("/auth/request-links/{token}", {
      params: { path: { token } }
    })

    if (error) {
      toast.error("Failed to revoke link")
    } else {
      toast.success("Link revoked successfully")
      fetchLinks()
    }
  }

  const copyToClipboard = (token: string) => {
    // Assuming the frontend runs on localhost:5173
    const url = `${window.location.origin}/request/${token}`
    navigator.clipboard.writeText(url)
    toast.success("Copied to clipboard!")
  }

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Public Request Links</h1>
          <p className="text-muted-foreground mt-1">
            Generate and manage password-less access links for your beneficiaries.
          </p>
        </div>
        <Button onClick={handleCreateLink} className="gap-2">
          <Plus className="h-4 w-4" /> Generate New Link
        </Button>
      </div>

      <Card className="shadow-sm border-stone-200">
        <CardHeader>
          <CardTitle>Active Links</CardTitle>
          <CardDescription>Hand these URLs out to beneficiaries to collect feedback.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Label / Token</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead className="text-right">Uses</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center h-24 text-muted-foreground">
                      Loading links...
                    </TableCell>
                  </TableRow>
                ) : links.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center h-24 text-muted-foreground">
                      No links generated yet.
                    </TableCell>
                  </TableRow>
                ) : (
                  links.map((link) => (
                    <TableRow key={link.token}>
                      <TableCell className="font-medium">
                        <div className="flex flex-col">
                          <span>{link.label}</span>
                          <span className="text-xs text-muted-foreground font-mono mt-1">
                            {link.token}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell>
                        {link.is_active ? (
                          <Badge variant="default" className="bg-emerald-500/10 text-emerald-600 hover:bg-emerald-500/20 border-emerald-200">Active</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-muted-foreground">Revoked</Badge>
                        )}
                      </TableCell>
                      <TableCell>{new Date(link.created_at).toLocaleDateString()}</TableCell>
                      <TableCell className="text-right font-mono">{link.uses}</TableCell>
                      <TableCell className="text-right space-x-2">
                        <Button 
                          variant="outline" 
                          size="sm" 
                          onClick={() => copyToClipboard(link.token)}
                          disabled={!link.is_active}
                        >
                          <Copy className="h-4 w-4 text-stone-500" />
                        </Button>
                        <Button 
                          variant="destructive" 
                          size="sm" 
                          onClick={() => handleRevoke(link.token)}
                          disabled={!link.is_active}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}