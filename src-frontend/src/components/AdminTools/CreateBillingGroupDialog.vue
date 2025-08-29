<template>
  <q-dialog v-model="show" persistent>
    <q-card style="min-width: 400px">
      <q-card-section>
        <div class="text-h6">{{ $t('adminTools.createBillingGroup') }}</div>
      </q-card-section>

      <q-card-section>
        <q-form @submit="createBillingGroup" class="q-gutter-md">
          <q-input
            v-model="form.name"
            :label="$t('adminTools.billingGroupName')"
            :rules="[
              (val) => !!val || $t('adminTools.billingGroupNameRequired'),
            ]"
            outlined
            dense
          />

          <q-select
            v-model="form.primary_member_id"
            :options="memberOptions"
            :label="$t('adminTools.selectPrimaryMember')"
            outlined
            dense
            clearable
            emit-value
            map-options
            option-value="id"
            option-label="name"
          />

          <div class="row justify-end q-gutter-sm">
            <q-btn
              :label="$t('button.cancel')"
              color="grey"
              @click="closeDialog"
              flat
            />
            <q-btn
              :label="$t('button.create')"
              type="submit"
              color="primary"
              :loading="loading"
            />
          </div>
        </q-form>
      </q-card-section>
    </q-card>
  </q-dialog>
</template>

<script>
import { defineComponent } from 'vue';

export default defineComponent({
  name: 'CreateBillingGroupDialog',
  props: {
    modelValue: {
      type: Boolean,
      default: false,
    },
    members: {
      type: Array,
      default: () => [],
    },
  },
  emits: ['update:modelValue', 'billing-group-created'],
  data() {
    return {
      loading: false,
      form: {
        name: '',
        primary_member_id: null,
      },
    };
  },
  computed: {
    show: {
      get() {
        return this.modelValue;
      },
      set(value) {
        this.$emit('update:modelValue', value);
      },
    },
    memberOptions() {
      return this.members.map((member) => ({
        id: member.id,
        name: member.name.full,
      }));
    },
  },
  methods: {
    async createBillingGroup() {
      this.loading = true;

      try {
        const response = await this.$axios.post(
          '/api/admin/billing-groups/',
          this.form
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.billingGroupCreated'),
          });

          this.$emit('billing-group-created', response.data.billing_group_id);
          this.closeDialog();
        } else {
          this.$q.notify({
            type: 'negative',
            message: response.data.message || this.$t('error.requestFailed'),
          });
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: this.$t('error.requestFailed'),
        });
      } finally {
        this.loading = false;
      }
    },

    closeDialog() {
      this.form = {
        name: '',
        primary_member_id: null,
      };
      this.show = false;
    },
  },
});
</script>
