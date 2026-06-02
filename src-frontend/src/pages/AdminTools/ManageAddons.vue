<template>
  <q-page class="column q-pa-md">
    <admin-addon-manager />
  </q-page>
</template>

<script lang="ts">
import AdminAddonManager from '@components/AdminTools/AdminAddonManager.vue';

export default {
  name: 'ManageAddonsPage',
  components: { AdminAddonManager },
};
</script>
