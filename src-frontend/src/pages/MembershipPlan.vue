<template>
  <q-page class="column flex justify-start items-center">
    <template v-if="currentPlan == false || canSignup == null">
      <q-spinner size="4em" />
    </template>

    <template v-else-if="!currentPlan && !isInBillingGroup">
      <select-tier />
    </template>

    <template v-else-if="!currentPlan && isInBillingGroup">
      <!-- Show billing group info for users in billing groups without individual plans -->
      <div class="q-mb-md full-width">
        <div class="text-h6 q-py-md">
          {{ $t('billing.youAreInBillingGroup') }}
        </div>
        <billing-group-manager />
      </div>
    </template>

    <template v-else>
      <template v-if="!canSignup">
        <div class="text-h6 q-pb-md">
          {{ $t('signup.requiredSteps') }}
        </div>

        <signup-required-steps />
      </template>

      <template v-else>
        <selected-tier :plan="currentPlan" :tier="currentTier" />

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

        <!-- Subscription Info and Cost Summary side by side -->
        <div
          v-if="
            this.subscriptionInfo?.currentPeriodEnd &&
            subscriptionStatus !== 'cancelling'
          "
          class="row q-col-gutter-md q-mb-md full-width"
        >
          <!-- Subscription Info Table (Left Side) -->
          <div class="col-12 col-md-6">
            <div class="text-h6 q-py-md">
              {{ $t('paymentPlans.subscriptionInfo') }}
            </div>
            <q-card>
              <q-list bordered separator>
                <q-item>
                  <q-item-section>
                    <q-item-label>{{ currentPeriodEnd }}</q-item-label>
                    <q-item-label caption>{{
                      $tc('paymentPlans.renewalDate')
                    }}</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item>
                  <q-item-section>
                    <q-item-label>{{ signupDate }}</q-item-label>
                    <q-item-label caption>{{
                      $tc('paymentPlans.signupDate')
                    }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </div>

          <!-- Cost Summary Table (Right Side) -->
          <div v-if="costSummary" class="col-12 col-md-6">
            <div class="text-h6 q-py-md">
              {{ costSummary.label }}
            </div>
            <q-card>
              <q-list bordered separator>
                <q-item
                  v-for="item in costSummary.line_items"
                  :key="item.description"
                >
                  <q-item-section>
                    <q-item-label>
                      {{ item.description }}
                      <span v-if="item.proration" class="text-orange">
                        (Prorated)</span
                      >
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-item-label>{{ item.cost_display }}</q-item-label>
                  </q-item-section>
                </q-item>
                <q-separator />
                <q-item>
                  <q-item-section>
                    <q-item-label class="text-weight-bold">Total</q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <q-item-label class="text-weight-bold">{{
                      costSummary.total_display
                    }}</q-item-label>
                  </q-item-section>
                </q-item>
                <q-item v-if="costSummary.amount_due !== costSummary.total">
                  <q-item-section>
                    <q-item-label class="text-weight-bold text-orange"
                      >Amount Due Now</q-item-label
                    >
                  </q-item-section>
                  <q-item-section side>
                    <q-item-label class="text-orange text-weight-bold">{{
                      costSummary.amount_due_display
                    }}</q-item-label>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card>
          </div>
        </div>

        <!-- Fallback: Show cost summary separately if no subscription info -->
        <div v-else-if="costSummary" class="q-mb-md full-width">
          <div class="text-h6 q-py-md">
            {{ costSummary.label }}
          </div>
          <q-card>
            <q-list bordered separator>
              <q-item
                v-for="item in costSummary.line_items"
                :key="item.description"
              >
                <q-item-section>
                  <q-item-label>
                    {{ item.description }}
                    <span v-if="item.proration" class="text-orange">
                      (Prorated)</span
                    >
                  </q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-item-label>{{ item.cost_display }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-separator />
              <q-item>
                <q-item-section>
                  <q-item-label class="text-weight-bold">Total</q-item-label>
                </q-item-section>
                <q-item-section side>
                  <q-item-label class="text-weight-bold">{{
                    costSummary.total_display
                  }}</q-item-label>
                </q-item-section>
              </q-item>
              <q-item v-if="costSummary.amount_due !== costSummary.total">
                <q-item-section>
                  <q-item-label class="text-weight-bold text-orange"
                    >Amount Due Now</q-item-label
                  >
                </q-item-section>
                <q-item-section side>
                  <q-item-label class="text-orange text-weight-bold">{{
                    costSummary.amount_due_display
                  }}</q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </q-card>
        </div>

        <!-- Billing Group Manager -->
        <div class="q-mb-md full-width">
          <div class="text-h6 q-py-md">
            {{ $t('billing.billingGroup') }}
          </div>
          <billing-group-manager />
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
      </template>
    </template>
  </q-page>
</template>

<script>
import { defineComponent } from 'vue';
import { mapGetters, mapActions } from 'vuex';
import SelectTier from '@components/Billing/SelectTier.vue';
import SelectedTier from '@components/Billing/SelectedTier.vue';
import SignupRequiredSteps from '@components/Billing/SignupRequiredSteps.vue';
import MemberBucksManageBilling from 'components/MemberBucksManageBilling.vue';
import BillingGroupManager from '@components/Billing/BillingGroupManager.vue';

export default defineComponent({
  name: 'MembershipTierPage',
  components: {
    MemberBucksManageBilling,
    SelectTier,
    SelectedTier,
    SignupRequiredSteps,
    BillingGroupManager,
  },
  data() {
    return {
      canSignup: null,
      disableButton: false,
      loadingButton: false,
      cancelSuccess: false,
      costSummary: null,
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
    currentPlan() {
      if (Object.keys(this.profile).length) {
        return this.profile.financial.membershipPlan;
      } else {
        return false;
      }
    },
    isInBillingGroup() {
      // Check if user is in a billing group - the backend returns null when not in a group
      return !!this.profile?.billingGroup;
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
  },
  methods: {
    ...mapActions('profile', ['getProfile']),
    getCostSummary() {
      this.$axios
        .get('/api/billing/membership-plan-cost-summary/')
        .then((result) => {
          if (result.data.success) {
            this.costSummary = result.data.upcoming_invoice;
          }
        })
        .catch(() => {
          // Silently fail if cost summary is not available
          this.costSummary = null;
        });
    },
    getSubscriptionInfo() {
      this.$axios.get('/api/billing/myplan/').then((result) => {
        if (result.data.success) {
          this.subscriptionInfo = result.data.subscription;
        }
      });
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
    this.getCostSummary();
    this.getSubscriptionInfo();
    this.getCanSignup();
  },
});
</script>
