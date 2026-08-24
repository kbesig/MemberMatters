<template>
  <q-banner
    v-if="pendingInvite"
    inline-actions
    rounded
    class="bg-primary text-white q-mb-md"
  >
    <template v-slot:avatar>
      <q-icon name="mdi-account-group" />
    </template>

    <div class="text-subtitle1 text-weight-bold">
      {{ $t('billingGroup.pendingInviteTitle') }}
    </div>
    <div class="q-mt-xs">
      {{
        $t('billingGroup.pendingInviteDescription', {
          groupName: pendingInvite.groupName,
          invitedBy: pendingInvite.invitedBy,
        })
      }}
    </div>
    <div v-if="hasActiveSubscription" class="q-mt-xs text-caption">
      {{ $t('billingGroup.pendingInviteWithSubscription') }}
    </div>

    <template v-slot:action>
      <q-btn
        flat
        :label="$t('billingGroup.declineInvite')"
        :loading="loadingDecline"
        :disable="loadingAccept || loadingDecline"
        @click="respond('decline')"
      />
      <q-btn
        flat
        :label="$t('billingGroup.acceptInvite')"
        :loading="loadingAccept"
        :disable="loadingAccept || loadingDecline"
        @click="confirmAccept"
      />
    </template>
  </q-banner>
</template>

<script lang="ts">
import { mapGetters } from 'vuex';

export default {
  name: 'BillingGroupInviteBanner',
  data() {
    return {
      pendingInvite: null as null | {
        groupName: string;
        invitedBy: string;
        billingGroupId: number;
      },
      loadingAccept: false,
      loadingDecline: false,
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    hasActiveSubscription() {
      const status = this.profile?.financial?.subscriptionState;
      return status === 'active' || status === 'cancelling';
    },
  },
  async mounted() {
    await this.fetchInvite();
  },
  methods: {
    async fetchInvite() {
      try {
        const result = await this.$axios.get('/api/billing/billing-group/');
        if (result.data.success && result.data.pendingInvite) {
          this.pendingInvite = result.data.pendingInvite;
        }
      } catch {
        // no invite
      }
    },
    confirmAccept() {
      if (this.hasActiveSubscription) {
        this.$q
          .dialog({
            title: this.$t('billingGroup.acceptInvite'),
            message: this.$t('billingGroup.pendingInviteWithSubscription'),
            cancel: this.$t('button.cancel'),
            persistent: true,
          })
          .onOk(() => this.respond('accept'));
      } else {
        this.respond('accept');
      }
    },
    async respond(action: 'accept' | 'decline') {
      if (action === 'accept') {
        this.loadingAccept = true;
      } else {
        this.loadingDecline = true;
      }

      try {
        const result = await this.$axios.post(
          '/api/billing/billing-group/invite/',
          { action }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t(
              action === 'accept'
                ? 'billingGroup.acceptSuccess'
                : 'billingGroup.declineSuccess'
            ),
          });
          this.pendingInvite = null;
          this.$emit('responded', action);
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t(
              action === 'accept'
                ? 'billingGroup.acceptFailed'
                : 'billingGroup.declineFailed'
            ),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t(
            action === 'accept'
              ? 'billingGroup.acceptFailed'
              : 'billingGroup.declineFailed'
          ),
        });
      } finally {
        this.loadingAccept = false;
        this.loadingDecline = false;
      }
    },
  },
};
</script>
