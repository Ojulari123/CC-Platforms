import { describe, expect, it } from "vitest";
import page from "~/pages/repositories.vue?raw";

/* The unfiled queue counted `unfiled.value?.items ?? []`, so a failed call read as zero and
   the page went on to say every repository has a department — a claim it had no standing to
   make. The query's own error flag now drives the copy. Asserted against the source because
   the page needs a Nuxt app and a query client to mount. */

describe("/repositories · a failed unfiled call is not an empty queue", () => {
  it("takes the error flag off the query rather than inferring it from the count", () => {
    expect(page).toMatch(/const \{ data: unfiled, isError: unfiledFailed \} = useQuery\(\{/);
    expect(page).toContain('queryKey: ["repositories", "unfiled"]');
  });

  it("says the queue could not be read instead of counting zero", () => {
    expect(page).toContain('<template v-if="unfiledFailed">The unfiled queue could not be read</template>');
    expect(page).toMatch(/<p v-if="unfiledFailed" role="alert"/);
  });

  it("keeps the genuinely-empty copy behind the failure branch", () => {
    expect(page).toMatch(/<p v-else-if="!needsFiling\.length"[\s\S]*?Every repository has a department/);
  });
});
