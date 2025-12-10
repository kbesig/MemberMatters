<template>
  <div v-if="pendingInvite" class="q-mb-md">
    <q-banner class="bg-info text-white">
      <template v-slot:avatar>
        <q-icon :name="icons.group" size="md" />
      </template>
      <div class="text-h6">{{ $t('billing.pendingInvite') }}</div>
      <p class="q-mb-md">
        {{ $t('billing.invitedToGroup', { name: pendingInvite.name }) }}
      </p>
      <div class="row q-gutter-sm">
        <q-btn
          :label="$t('billing.button.accept')"
          color="positive"
          @click="respondToInvite('accept')"
          :loading="loading"
        />
        <q-btn
          :label="$t('billing.button.decline')"
          color="negative"
          @click="respondToInvite('decline')"
          :loading="loading"
        />
      </div>
    </q-banner>
  </div>
</template>

<script>
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';
import icons from '@icons';

export default defineComponent({
  name: 'BillingGroupInviteBanner',
  data() {
    return {
      loading: false,
      pendingInvite: null,
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    icons() {
      return icons;
    },
  },
  methods: {
    async loadBillingGroupInvite() {
      try {
        const response = await this.$axios.get('/api/billing/billing-group/');
        if (response.data.success) {
          this.pendingInvite = response.data.pending_invite;
        }
      } catch (error) {
        // Silently fail - this is just checking for an invite
        console.error('Error checking for billing group invite:', error);
      }
    },

    async respondToInvite(action) {
      // If accepting and user has an active subscription, show warning dialog
      if (
        action === 'accept' &&
        this.profile.financial.subscriptionState === 'active'
      ) {
        this.$q
          .dialog({
            title: this.$t('billing.confirmAcceptInvite'),
            message: this.$t('billing.subscriptionCancellationWarning'),
            cancel: true,
            persistent: true,
            color: 'warning',
          })
          .onOk(() => {
            this.processInviteResponse(action);
          });
      } else {
        this.processInviteResponse(action);
      }
    },

    async processInviteResponse(action) {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          '/api/billing/billing-group/invite/',
          { action }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message:
              action === 'accept'
                ? this.$t('billing.inviteAccepted')
                : this.$t('billing.inviteDeclined'),
          });

          // Refresh profile to update subscription status
          await this.$store.dispatch('profile/getProfile');

          // Clear the pending invite
          this.pendingInvite = null;

          // Emit event so parent components can react
          this.$emit('invite-responded', action);

          // If user accepted, redirect to membership plan page to see their new billing group
          if (action === 'accept') {
            this.$router.push({ name: 'membershipPlan' });
          }
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
  },
  mounted() {
    this.loadBillingGroupInvite();
  },
});
</script>
