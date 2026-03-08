<template>
  <q-page class="column flex justify-start items-center">
    <admin-shelf-management style="width: 100%; max-width: 1400px" />
  </q-page>
</template>

<script>
import AdminShelfManagement from '@components/AdminTools/AdminShelfManagement.vue';

export default {
  name: 'ManageShelvesPage',
  components: {
    AdminShelfManagement,
  },
};
</script>
