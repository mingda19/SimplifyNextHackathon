// src/routes/request.tsx
//
// The signed-in recipient's version of the intake form. The anonymous
// link-based variant lives in request.$token.tsx. Phase 3 of the port adds the
// multilingual copy and speech input to both.
import { createFileRoute, redirect, useNavigate } from "@tanstack/react-router";
import { useState } from "react";
import { CheckCircle2, HeartHandshake } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { feedbackClient, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export const Route = createFileRoute("/request")({
  beforeLoad: ({ context }) => {
    if (!context.auth.user) throw redirect({ to: "/login" });
  },
  component: RequestPage,
});

function RequestPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setIsSubmitting(true);

    const { error } = await feedbackClient.POST("/feedback", {
      body: {
        beneficiary_id: user?.beneficiary_id ?? user?.id ?? "",
        text,
        lang: "en",
        channel: "web",
      },
    });

    setIsSubmitting(false);
    if (error) {
      toast.error(errorMessage(error, "Could not send your request. Please try again."));
      return;
    }
    setIsSuccess(true);
  };

  if (isSuccess) {
    return (
      <div className="flex min-h-svh items-center justify-center bg-muted/40 p-4">
        <Card className="w-full max-w-md text-center">
          <CardHeader className="space-y-4">
            <CheckCircle2 className="mx-auto size-16 text-primary" />
            <CardTitle className="text-2xl">Request sent</CardTitle>
            <CardDescription className="text-lg">
              We have received your message. The charity will review your needs shortly.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Button
              variant="outline"
              className="h-12 w-full text-base"
              onClick={() => {
                setText("");
                setIsSuccess(false);
              }}
            >
              Send another request
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-svh flex-col items-center justify-center bg-muted/40 p-4">
      <div className="mb-6 flex flex-col items-center text-center">
        <div className="mb-4 flex size-16 items-center justify-center rounded-2xl bg-primary/10">
          <HeartHandshake className="size-8 text-primary" />
        </div>
        <h1 className="mb-1 text-2xl font-bold tracking-tight">Request form</h1>
        <p className="max-w-sm text-muted-foreground">
          Tell us what you need this week.
        </p>
      </div>

      <Card className="w-full max-w-md">
        <CardContent className="pt-6">
          <form onSubmit={handleSubmit} className="space-y-6">
            <div className="space-y-3">
              <label htmlFor="text" className="block text-lg leading-tight font-medium">
                What items do you and your family need most right now?
              </label>
              <Textarea
                id="text"
                placeholder="e.g. 'We need baby formula and diapers size 4. Also running low on rice.'"
                className="min-h-[170px] resize-none p-4 text-lg"
                value={text}
                onChange={(e) => setText(e.target.value)}
                required
              />
            </div>
            <Button type="submit" className="h-14 w-full text-lg font-medium" disabled={isSubmitting}>
              {isSubmitting ? "Sending…" : "Submit request"}
            </Button>
          </form>
        </CardContent>
      </Card>

      <Button
        variant="ghost"
        size="sm"
        className="mt-6"
        onClick={() => {
          logout();
          navigate({ to: "/login", replace: true });
        }}
      >
        Sign out
      </Button>
    </div>
  );
}
