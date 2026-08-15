<template>
  <!-- Background only. Ink and font already come from the shared layer's tokens.css
       (`body { color: var(--ink) }`), so a screen that is not dark has to say so for
       itself — see the text colour on /login and /signup. -->
  <div class="min-h-screen bg-app">
    <NuxtLayout>
      <NuxtPage />
    </NuxtLayout>
  </div>
</template>
