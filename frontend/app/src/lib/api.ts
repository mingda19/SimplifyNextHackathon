// src/lib/api.ts
import createClient from "openapi-fetch";
import type { paths as AuthPaths } from "./schema";
import type { paths as FeedbackPaths } from "./feedback-schema";
import type { paths as InventoryPaths } from "./inventory-schema";
import type { paths as OrchestratorPaths } from "./orchestrator-schema"; // <-- Add this

export const client = createClient<AuthPaths>({ baseUrl: "http://localhost:8001" });
export const feedbackClient = createClient<FeedbackPaths>({ baseUrl: "http://localhost:8002" });
export const inventoryClient = createClient<InventoryPaths>({ baseUrl: "http://localhost:8000" });

// Add the Orchestrator client (Port 8003)
export const orchestratorClient = createClient<OrchestratorPaths>({ baseUrl: "http://localhost:8003" });

const authInterceptor = {
  onRequest({ request }: { request: Request }) {
    const token = localStorage.getItem("pantry_token");
    if (token) request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  }
};

client.use(authInterceptor);
feedbackClient.use(authInterceptor);
inventoryClient.use(authInterceptor);
orchestratorClient.use(authInterceptor); 