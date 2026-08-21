<template>
  <q-dialog ref="dialogRef" @hide="onDialogHide">
    <q-card style="min-width: 350px">
      <q-card-section class="row items-center q-pb-none">
        <div class="text-h6">{{ $t('billingGroup.createGroup') }}</div>
        <q-space />
        <q-btn icon="mdi-close" flat round dense @click="onDialogCancel" />
      </q-card-section>

      <q-card-section>
        <p>{{ $t('billingGroup.createGroupDescription') }}</p>
        <q-input
          v-model="groupName"
          :label="$t('billingGroup.groupName')"
          outlined
          autofocus
          @keyup.enter="submit"
        />
      </q-card-section>

      <q-card-actions align="right">
        <q-btn flat :label="$t('button.cancel')" @click="onDialogCancel" />
        <q-btn
          color="primary"
          :label="$t('billingGroup.createGroup')"
          :loading="loading"
          :disable="!groupName.trim()"
          @click="submit"
        />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script lang="ts">
import { useDialogPluginComponent } from 'quasar';

export default {
  name: 'CreateBillingGroupDialog',
  emits: [...useDialogPluginComponent.emits],
  setup() {
    const { dialogRef, onDialogHide, onDialogOK, onDialogCancel } =
      useDialogPluginComponent();
    return { dialogRef, onDialogHide, onDialogOK, onDialogCancel };
  },
  data() {
    return {
      groupName: '',
      loading: false,
    };
  },
  methods: {
    async submit() {
      if (!this.groupName.trim()) return;
      this.loading = true;
      try {
        const result = await this.$axios.post('/api/billing/billing-group/', {
          name: this.groupName.trim(),
        });
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.createGroupSuccess'),
          });
          this.onDialogOK(result.data.billingGroup);
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.createGroupFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.createGroupFailed'),
        });
      } finally {
        this.loading = false;
      }
    },
  },
};
</script>
