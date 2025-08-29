<template>
  <q-page class="column flex content-center justify-start">
    <manage-addons />
  </q-page>
</template>

<script lang="ts">
import { defineComponent } from 'vue';
import ManageAddons from '@components/AdminTools/ManageAddons.vue';

export default defineComponent({
  name: 'AddOnsPage',
  components: { ManageAddons },
});
</script>
