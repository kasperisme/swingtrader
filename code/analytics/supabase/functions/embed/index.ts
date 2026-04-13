// Supabase Edge Function: embed
// Generates a gte-small embedding for a single input string.
// Docs: https://supabase.com/docs/guides/ai/quickstarts/generate-text-embeddings

const session = new Supabase.ai.Session("gte-small");

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "authorization, x-client-info, apikey, content-type",
};

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { input } = await req.json();
    const text = typeof input === "string" ? input.trim() : "";
    if (!text) {
      return new Response(
        JSON.stringify({ error: "input is required" }),
        { status: 400, headers: { ...corsHeaders, "Content-Type": "application/json" } },
      );
    }

    const embedding = await session.run(text, {
      mean_pool: true,
      normalize: true,
    });

    return new Response(
      JSON.stringify({ embedding }),
      { headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  } catch (error) {
    return new Response(
      JSON.stringify({ error: error instanceof Error ? error.message : "Unknown error" }),
      { status: 500, headers: { ...corsHeaders, "Content-Type": "application/json" } },
    );
  }
});
