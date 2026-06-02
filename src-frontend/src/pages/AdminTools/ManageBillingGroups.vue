<template>
  <q-page class="column q-pa-md">
    <admin-billing-group-manager />
  </q-page>
</template>

<script lang="ts">
import AdminBillingGroupManager from '@components/AdminTools/AdminBillingGroupManager.vue';

export default {
  name: 'ManageBillingGroupsPage',
  components: { AdminBillingGroupManager },
};
</script>
