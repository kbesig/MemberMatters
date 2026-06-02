<template>
  <q-page class="row flex content-start justify-center">
    <div v-if="loggedIn">
      <div class="column flex content-start justify-center">
        <q-banner
          v-if="
            profile.memberStatus !== 'active' &&
            profile.memberStatus !== 'accountonly'
          "
          inline-actions
          rounded
          class="bg-orange text-white q-ma-md"
        >
          <template v-slot:avatar>
            <q-icon :name="icons.warning" />
          </template>
          {{ $t('access.inactive') }}
        </q-banner>

        <q-banner
          v-if="subscriptionStatus === 'group_inactive'"
          inline-actions
          rounded
          class="bg-negative text-white q-ma-md"
        >
          <template v-slot:avatar>
            <q-icon name="mdi-alert-circle" />
          </template>
          <div class="text-subtitle1 text-weight-bold">
            {{ $t('paymentPlans.groupInactiveTitle') }}
          </div>
          <div>{{ $t('paymentPlans.groupInactiveDescription') }}</div>
        </q-banner>
      </div>

      <div class="q-px-md q-pb-sm">
        <q-chip
          :color="subscriptionStatusColor"
          text-color="white"
          :icon="subscriptionStatusIcon"
        >
          {{ $t(`adminTools.subscriptionStatusString.${subscriptionStatus}`) }}
        </q-chip>
      </div>

      <div class="q-px-md q-pb-sm">
        <billing-group-invite-banner @responded="getProfile" />
      </div>

      <h5 class="q-ma-md">
        {{ $t('dashboard.quickCards') }}
      </h5>
      <div class="row">
        <quick-cards />
      </div>

      <h5 class="q-ma-md">
        {{ $t('dashboard.usefulResources') }}
      </h5>
      <div class="row flex items-stretch justify-start">
        <dashboard-card
          v-for="card in homepageCards"
          :key="card.title"
          class="col-12 col-sm-4"
          :title="card.title"
          :icon="card.icon"
          :description="card.description"
          :link-text="card.btn_text"
          :link-location="card.url"
          :router-link="card.routerLink ? card.routerLink : false"
          :links="card.links"
        />
      </div>
    </div>
  </q-page>
</template>

<script>
import { mapGetters, mapActions } from 'vuex';
import QuickCards from '@components/QuickCards.vue';
import { Platform } from 'quasar';
import DashboardCard from '@components/DashboardCard.vue';
import icons from 'src/icons';
import BillingGroupInviteBanner from '@components/Billing/BillingGroupInviteBanner.vue';

export default {
  name: 'DashboardPage',
  components: { QuickCards, DashboardCard, BillingGroupInviteBanner },
  computed: {
    Platform() {
      return Platform;
    },
    ...mapGetters('config', ['homepageCards', 'features']),
    ...mapGetters('profile', ['loggedIn', 'profile']),
    icons() {
      return icons;
    },
    subscriptionStatus() {
      return this.profile?.financial?.subscriptionState;
    },
    subscriptionStatusColor() {
      const map = {
        active: 'positive',
        group_active: 'positive',
        cancelling: 'warning',
        inactive: 'negative',
        group_inactive: 'negative',
      };
      return map[this.subscriptionStatus] ?? 'grey';
    },
    subscriptionStatusIcon() {
      const map = {
        active: 'mdi-check-circle',
        group_active: 'mdi-account-group',
        cancelling: 'mdi-clock-alert',
        inactive: 'mdi-cancel',
        group_inactive: 'mdi-alert-circle',
      };
      return map[this.subscriptionStatus] ?? 'mdi-help-circle';
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
  },
  async mounted() {
    await this.getProfile();
    if (
      this.profile.memberStatus === 'noob' &&
      this.$route.name !== 'membershipPlan' &&
      this.features.enableMembershipPayments
    ) {
      this.$router.push({ name: 'membershipPlan' });
    }
  },
};
</script>

<style lang="sass" scoped>
.row
  width: 100%
  max-width: $maxWidth
  margin: auto
</style>
