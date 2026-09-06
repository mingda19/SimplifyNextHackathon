// src/routes/feedback.tsx
import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { feedbackClient } from "@/lib/api";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { MessageSquare, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

export const Route = createFileRoute("/feedback")({
  component: FeedbackPage,
});

function FeedbackPage() {
  const [feedback, setFeedback] = useState<any[]>([]);
  const [unmetNeeds, setUnmetNeeds] = useState<any[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      setIsLoading(true);

      // Fetch both endpoints simultaneously from port 8002
      const [feedbackRes, needsRes] = await Promise.all([
        feedbackClient.GET("/feedback"),
        feedbackClient.GET("/feedback/unmet-needs"),
      ]);

      if (feedbackRes.error || needsRes.error) {
        toast.error("Failed to load feedback data");
      } else {
        setFeedback(Array.isArray(feedbackRes.data) ? feedbackRes.data : []);
        setUnmetNeeds(Array.isArray(needsRes.data) ? needsRes.data : []);
      }

      setIsLoading(false);
    };

    fetchData();
  }, []);

  // Helper to color-code urgency (Assuming 1-5 scale)
  const getUrgencyBadge = (urgency: number) => {
    if (urgency >= 4) return <Badge variant="destructive">High Urgency</Badge>;
    if (urgency === 3)
      return <Badge className="bg-amber-500 hover:bg-amber-600">Medium</Badge>;
    return <Badge variant="secondary">Low</Badge>;
  };

  return (
    <div className="p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">
            Beneficiary Insights
          </h1>
          <p className="text-muted-foreground mt-1">
            AI-extracted needs and real-time feedback analysis.
          </p>
        </div>
      </div>

      <Tabs defaultValue="needs" className="w-full">
        <TabsList className="grid w-full max-w-[400px] grid-cols-2">
          <TabsTrigger value="needs">Aggregated Needs</TabsTrigger>
          <TabsTrigger value="raw">Raw Feedback</TabsTrigger>
        </TabsList>

        {/* TAB 1: UNMET NEEDS */}
        <TabsContent value="needs" className="mt-6">
          <Card className="shadow-sm border-stone-200">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <AlertTriangle className="h-5 w-5 text-amber-500" />
                Current Shortages
              </CardTitle>
              <CardDescription>
                Items requested by beneficiaries that are not currently mapped
                to sufficient inventory.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Requested Item</TableHead>
                    <TableHead className="text-center">Request Count</TableHead>
                    <TableHead className="text-right">AI Confidence</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {isLoading ? (
                    <TableRow>
                      <TableCell colSpan={3} className="text-center py-8">
                        Analyzing...
                      </TableCell>
                    </TableRow>
                  ) : unmetNeeds.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={3}
                        className="text-center py-8 text-stone-500"
                      >
                        No current shortages detected.
                      </TableCell>
                    </TableRow>
                  ) : (
                    unmetNeeds.map((item, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-semibold text-stone-800 capitalize">
                          {item.need}
                          {item.gap && (
                            <Badge
                              variant="outline"
                              className="ml-2 text-xs border-amber-200 text-amber-700 bg-amber-50"
                            >
                              Supply Gap
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-center font-mono">
                          {item.count}
                        </TableCell>
                        <TableCell className="text-right w-[200px]">
                          <div className="flex items-center justify-end gap-3">
                            <span className="text-sm font-medium">
                              {Math.round(item.avg_confidence * 100)}%
                            </span>
                            <Progress
                              value={item.avg_confidence * 100}
                              className="w-[60px] h-2"
                            />
                          </div>
                        </TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* TAB 2: RAW FEEDBACK */}
        <TabsContent value="raw" className="mt-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {isLoading ? (
              <p className="p-4">Loading feedback...</p>
            ) : feedback.length === 0 ? (
              <p className="p-4 text-stone-500">No feedback received yet.</p>
            ) : (
              feedback.map((item) => (
                <Card
                  key={item.id}
                  className="shadow-sm border-stone-200 flex flex-col"
                >
                  <CardHeader className="pb-3">
                    <div className="flex justify-between items-start mb-2">
                      <Badge
                        variant="outline"
                        className="bg-stone-50 font-mono text-xs"
                      >
                        {item.beneficiary_id}
                      </Badge>
                      {getUrgencyBadge(item.urgency)}
                    </div>
                    <CardTitle className="text-lg leading-tight">
                      {item.summary_en || "Processing summary..."}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex-1 flex flex-col justify-between">
                    <div className="space-y-4">
                      <div className="bg-stone-50 p-3 rounded-lg text-sm text-stone-600 italic border border-stone-100 relative">
                        <MessageSquare className="h-4 w-4 absolute top-3 right-3 text-stone-300" />
                        "{item.text}"
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {item.categories?.map((cat: string) => (
                          <Badge
                            key={cat}
                            variant="secondary"
                            className="text-[10px] uppercase tracking-wider"
                          >
                            {cat}
                          </Badge>
                        ))}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
