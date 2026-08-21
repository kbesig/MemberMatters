<template>
  <q-page class="column flex justify-start items-center">
    <template v-if="currentPlan == false || canSignup == null">
      <q-spinner size="4em" />
    </template>

    <template v-else-if="subscriptionStatus === 'group_inactive'">
      <div class="q-pa-md full-width" style="max-width: 700px">
        <q-banner class="bg-negative text-white q-mb-md" rounded>
          <template v-slot:avatar>
            <q-icon name="mdi-alert-circle" />
          </template>
          <div class="text-h6">
            {{ $t('paymentPlans.groupInactiveTitle') }}
          </div>
          <p class="q-mb-none">
            {{ $t('paymentPlans.groupInactiveDescription') }}
          </p>
        </q-banner>
      </div>
    </template>

    <template v-else-if="subscriptionStatus === 'group_active'">
      <div class="q-pa-md full-width" style="max-width: 700px">
        <q-banner class="bg-positive text-white q-mb-md" rounded>
          <template v-slot:avatar>
            <q-icon name="mdi-account-group" />
          </template>
          <div class="text-h6">
            {{ $t('paymentPlans.groupActiveTitle') }}
          </div>
          <p class="q-mb-none">
            {{ $t('paymentPlans.groupActiveDescription') }}
          </p>
        </q-banner>
      </div>
    </template>

    <template v-else-if="!currentPlan">
      <template
        v-if="profile.pendingBillingGroupInvite && inviteStatus === 'valid'"
      >
        <div class="q-pa-md full-width" style="max-width: 600px">
          <q-banner class="bg-primary text-white q-mb-md" rounded>
            <template v-slot:avatar>
              <q-icon name="mdi-account-group" />
            </template>
            <div class="text-h6">
              {{ $t('billingGroup.pendingInviteTitle') }}
            </div>
            <p class="q-mb-none">
              {{ $t('billingGroup.pendingInviteNewMemberDescription') }}
            </p>
          </q-banner>

          <div v-if="completeSignupError" class="q-mb-md">
            <q-banner class="bg-negative text-white" rounded>{{
              completeSignupError
            }}</q-banner>
          </div>

          <signup-required-steps v-if="!canSignup" />

          <q-btn
            v-else
            color="primary"
            :loading="loadingButton"
            :label="$t('billingGroup.acceptInvite')"
            @click="completeGroupInviteSignup"
          />
        </div>
      </template>
      <template
        v-else-if="
          profile.pendingBillingGroupInvite && inviteStatus !== 'valid'
        "
      >
        <div class="q-pa-md full-width" style="max-width: 600px">
          <q-banner class="bg-warning text-white q-mb-md" rounded>
            <template v-slot:avatar>
              <q-icon name="mdi-account-remove" />
            </template>
            <div class="text-h6">
              {{ $t('billingGroup.inviteRevokedTitle') }}
            </div>
            <p class="q-mb-none">
              {{ $t(`billingGroup.inviteRevoked_${inviteStatus}`) }}
            </p>
          </q-banner>
          <q-btn
            color="primary"
            :label="$t('billingGroup.signupWithoutGroup')"
            @click="skipGroupInvite = true"
          />
        </div>
      </template>
      <template v-else>
        <select-tier />
      </template>
    </template>

    <template v-else>
      <template v-if="!canSignup">
        <div class="text-h6 q-pb-md">
          {{ $t('signup.requiredSteps') }}
        </div>

        <signup-required-steps />
      </template>

      <template v-else>
        <!-- Upcoming bill table -->
        <div class="text-h6 q-pb-sm">
          {{ $t('paymentPlans.upcomingInvoice') }}
        </div>
        <subscription-cost-summary />

        <!-- Subscription summary table (mirrors admin billing tab) -->
        <template v-if="subscriptionInfo?.currentPeriodEnd">
          <div class="text-h6 q-pb-sm">
            {{ $t('paymentPlans.subscriptionInfo') }}
          </div>

          <!-- Desktop table -->
          <q-markup-table
            bordered
            padding
            class="rounded-borders desktop-only q-mb-md full-width"
          >
            <thead>
              <tr>
                <th class="text-left">
                  {{ $t('paymentPlans.membershipTier') }}
                </th>
                <th class="text-left">{{ $t('paymentPlans.billingPlan') }}</th>
                <th class="text-left">{{ $t('paymentPlans.billingDate') }}</th>
                <th class="text-left">{{ $t('paymentPlans.signupDate') }}</th>
                <th class="text-left">{{ $t('paymentPlans.renewalDate') }}</th>
                <template v-if="subscriptionInfo.cancelAt">
                  <th class="text-left">{{ $t('paymentPlans.cancelsOn') }}</th>
                </template>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="text-left">{{ currentTier.name }}</td>
                <td class="text-left">
                  {{
                    $t('paymentPlans.intervalDescription', {
                      currency: currentPlan.currency.toUpperCase(),
                      amount: $n(
                        currentPlan.cost / 100,
                        'currency',
                        siteLocaleCurrency
                      ),
                      interval: $tc(
                        `paymentPlans.interval.${currentPlan.interval.toLowerCase()}`,
                        currentPlan.intervalAmount
                      ),
                    })
                  }}
                </td>
                <td class="text-left">{{ billingCycleAnchorDate }}</td>
                <td class="text-left">{{ signupDate }}</td>
                <td class="text-left">{{ currentPeriodEnd }}</td>
                <template v-if="subscriptionInfo.cancelAt">
                  <td class="text-left">{{ cancelAtDate }}</td>
                </template>
              </tr>
            </tbody>
          </q-markup-table>

          <!-- Mobile list -->
          <q-list
            bordered
            padding
            class="rounded-borders desktop-hide q-mb-md"
            style="max-width: 350px"
          >
            <q-item>
              <q-item-section>
                <q-item-label lines="1">
                  <q-chip
                    :color="
                      subscriptionStatus === 'active'
                        ? 'positive'
                        : subscriptionStatus === 'cancelling'
                        ? 'warning'
                        : 'negative'
                    "
                    text-color="white"
                    dense
                  >
                    {{ subscriptionStatus }}
                  </q-chip>
                </q-item-label>
                <q-item-label caption>{{
                  $t('adminTools.subscriptionStatus')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label lines="1">{{ currentTier.name }}</q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.membershipTier')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label lines="1">
                  {{
                    $t('paymentPlans.intervalDescription', {
                      currency: currentPlan.currency.toUpperCase(),
                      amount: $n(
                        currentPlan.cost / 100,
                        'currency',
                        siteLocaleCurrency
                      ),
                      interval: $tc(
                        `paymentPlans.interval.${currentPlan.interval.toLowerCase()}`,
                        currentPlan.intervalAmount
                      ),
                    })
                  }}
                </q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.billingPlan')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label lines="1">{{
                  billingCycleAnchorDate
                }}</q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.billingDate')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label lines="1">{{ signupDate }}</q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.signupDate')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item>
              <q-item-section>
                <q-item-label lines="1">{{ currentPeriodEnd }}</q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.renewalDate')
                }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-item v-if="subscriptionInfo.cancelAt">
              <q-item-section>
                <q-item-label lines="1">{{ cancelAtDate }}</q-item-label>
                <q-item-label caption>{{
                  $t('paymentPlans.cancelsOn')
                }}</q-item-label>
              </q-item-section>
            </q-item>
          </q-list>
        </template>

        <div v-if="cancelSuccess" class="row q-mb-md">
          <q-banner class="bg-success text-white">
            <div class="text-h5">{{ $tc('actionSuccess') }}</div>
            <p>{{ $tc('paymentPlans.cancelSuccessDescription') }}</p>
          </q-banner>
        </div>

        <div v-if="subscriptionStatus === 'cancelling'" class="row q-mb-md">
          <q-banner class="bg-error text-white">
            <div class="text-h5">{{ $tc('paymentPlans.cancelling') }}</div>
            <p>
              {{
                $t('paymentPlans.cancellingDescription', { date: cancelAtDate })
              }}
            </p>
          </q-banner>
        </div>

        <q-btn
          v-if="subscriptionStatus === 'active'"
          :disable="disableButton"
          :loading="loadingButton"
          @click="cancelPlan"
          color="error"
          :label="$tc('paymentPlans.cancelButton')"
        />
        <member-bucks-manage-billing v-else-if="!cardExists" />
        <q-btn
          v-else
          :disable="disableButton"
          :loading="loadingButton"
          @click="resumePlan"
          color="success"
          :label="$tc('paymentPlans.resumeButton')"
        />

        <div class="q-mt-lg full-width">
          <div class="text-h6 q-pb-md">{{ $t('billingGroup.title') }}</div>
          <billing-group-invite-banner @responded="getProfile" />
          <billing-group-manager />
        </div>

        <div class="q-mt-lg">
          <div class="text-h6 q-pb-md">{{ $t('addons.activeAddons') }}</div>
          <member-addon-manager />
        </div>

        <div class="q-mt-lg">
          <div class="text-h6 q-pb-md">{{ $t('shelfRental.myShelf') }}</div>
          <shelf-rental-manager />
        </div>
      </template>
    </template>
  </q-page>
</template>

<script>
import { defineComponent } from 'vue';
import { mapGetters, mapActions } from 'vuex';
import SelectTier from '@components/Billing/SelectTier.vue';
import SignupRequiredSteps from '@components/Billing/SignupRequiredSteps.vue';
import MemberBucksManageBilling from 'components/MemberBucksManageBilling.vue';
import BillingGroupInviteBanner from '@components/Billing/BillingGroupInviteBanner.vue';
import BillingGroupManager from '@components/Billing/BillingGroupManager.vue';
import MemberAddonManager from '@components/Billing/MemberAddonManager.vue';
import ShelfRentalManager from '@components/Billing/ShelfRentalManager.vue';
import SubscriptionCostSummary from '@components/Billing/SubscriptionCostSummary.vue';

export default defineComponent({
  name: 'MembershipTierPage',
  components: {
    MemberBucksManageBilling,
    SelectTier,
    SignupRequiredSteps,
    BillingGroupInviteBanner,
    BillingGroupManager,
    MemberAddonManager,
    ShelfRentalManager,
    SubscriptionCostSummary,
  },
  data() {
    return {
      canSignup: null,
      disableButton: false,
      loadingButton: false,
      cancelSuccess: false,
      completeSignupError: '',
      skipGroupInvite: false,
      subscriptionInfo: {
        billingCycleAnchor: null,
        currentPeriodEnd: null,
        cancelAt: null,
        cancelAtPeriodEnd: null,
        startDate: null,
      },
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['siteLocaleCurrency']),
    currentPlan() {
      if (Object.keys(this.profile).length) {
        return this.profile.financial.membershipPlan;
      } else {
        return false;
      }
    },
    cardExists() {
      return this?.profile?.financial?.memberBucks?.savedCard?.last4;
    },
    currentTier() {
      return this.profile.financial.membershipTier;
    },
    subscriptionStatus() {
      return this.profile.financial.subscriptionState;
    },
    inviteStatus() {
      if (this.skipGroupInvite) return null;
      return this.profile.pendingBillingGroupInviteStatus || null;
    },
    currentPeriodEnd() {
      return new Date(
        this.subscriptionInfo?.currentPeriodEnd * 1000
      ).toLocaleString('en-au');
    },
    signupDate() {
      return new Date(this.subscriptionInfo?.startDate * 1000).toLocaleString(
        'en-au'
      );
    },
    cancelAtDate() {
      return new Date(this.subscriptionInfo?.cancelAt * 1000).toLocaleString(
        'en-au'
      );
    },
    billingCycleAnchorDate() {
      return new Date(
        this.subscriptionInfo?.billingCycleAnchor * 1000
      ).toLocaleString('en-au');
    },
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
    getSubscriptionInfo() {
      this.$axios.get('/api/billing/myplan/').then((result) => {
        if (result.data.success) {
          this.subscriptionInfo = result.data.subscription;
        }
      });
    },
    async completeGroupInviteSignup() {
      this.loadingButton = true;
      this.completeSignupError = '';
      try {
        const result = await this.$axios.post('/api/billing/complete-signup/');
        if (result.data.success) {
          await this.getProfile();
          this.$router.push({ name: 'dashboard' });
        } else {
          this.completeSignupError = this.$t(
            result.data.message || 'error.requestFailed'
          );
        }
      } catch {
        this.completeSignupError = this.$t('error.requestFailed');
      } finally {
        this.loadingButton = false;
      }
    },
    getCanSignup() {
      this.$axios
        .get('/api/billing/can-signup/')
        .then((result) => {
          if (result.data.success) {
            this.canSignup = true;
          } else {
            this.canSignup = false;
          }
        })
        .catch(() => {
          this.$q
            .dialog({
              title: this.$t('error.requestFailed'),
              message: this.$t('error.contactUs'),
            })
            .onDismiss(() => this.$router.push({ name: 'dashboard' }));
        });
    },
    cancelPlan() {
      this.$q
        .dialog({
          title: this.$t('confirmAction'),
          message: this.$t('paymentPlans.cancelConfirmDescription'),
          cancel: this.$t('button.back'),
          persistent: true,
        })
        .onOk(() => {
          this.disableButton = true;
          this.loadingButton = true;
          this.$axios
            .post('/api/billing/myplan/cancel/')
            .then((result) => {
              if (result.data.success) {
                this.cancelSuccess = true;
                setTimeout(() => {
                  location.reload();
                }, 3000);
              } else {
                this.$q.dialog({
                  title: this.$t('paymentPlans.cancelFailed'),
                  message: this.$t('error.contactUs'),
                });
                this.disableButton = false;
              }
            })
            .catch(() => {
              this.$q.dialog({
                title: this.$t('paymentPlans.cancelFailed'),
                message: this.$t('error.contactUs'),
              });
              this.disableButton = false;
            })
            .finally(() => {
              this.loadingButton = false;
            });
        });
    },
    resumePlan() {
      this.disableButton = true;
      this.loadingButton = true;
      this.$axios
        .post('/api/billing/myplan/resume/')
        .then((result) => {
          if (result.data.success) {
            location.reload();
          } else {
            this.$q.dialog({
              title: this.$t('paymentPlans.resumeFailed'),
              message: this.$t('error.contactUs'),
            });
            this.disableButton = false;
          }
        })
        .catch(() => {
          this.$q.dialog({
            title: this.$t('paymentPlans.resumeFailed'),
            message: this.$t('error.contactUs'),
          });
          this.disableButton = false;
        })
        .finally(() => {
          this.loadingButton = false;
        });
    },
  },
  mounted() {
    this.getProfile();
    this.getSubscriptionInfo();
    this.getCanSignup();
  },
});
</script>
