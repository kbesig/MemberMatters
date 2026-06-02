<template>
  <q-page class="column q-pa-md">
    <admin-shelf-management />
  </q-page>
</template>

<script lang="ts">
import AdminShelfManagement from '@components/AdminTools/AdminShelfManagement.vue';

export default {
  name: 'ManageShelvesPage',
  components: { AdminShelfManagement },
};
</script>
