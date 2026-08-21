<template>
  <div>
    <q-spinner v-if="loading" size="2em" />

    <template v-else-if="billingGroup">
      <!-- In a group -->
      <q-card flat bordered class="q-mb-md full-width">
        <q-card-section>
          <div class="text-h6">
            {{ $t('billingGroup.title') }}: {{ billingGroup.name }}
          </div>
        </q-card-section>

        <q-separator />

        <!-- Desktop table -->
        <q-markup-table
          bordered
          padding
          class="rounded-borders desktop-only full-width"
        >
          <thead>
            <tr>
              <th class="text-left">{{ $t('adminTools.memberName') }}</th>
              <th class="text-left">{{ $t('adminTools.addonName') }}</th>
              <th class="text-left">{{ $t('adminTools.cost') }}</th>
              <th v-if="billingGroup.isPrimaryMember"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="member in billingGroup.members" :key="member.id">
              <td class="text-left">
                {{ member.name }}
                <q-chip
                  v-if="member.isPrimary"
                  dense
                  size="sm"
                  color="primary"
                  text-color="white"
                  class="q-ml-xs"
                >
                  {{ $t('billingGroup.isPrimary') }}
                </q-chip>
              </td>
              <td class="text-left">{{ member.addonName ?? '\u2014' }}</td>
              <td class="text-left">
                <span v-if="member.lockedCost != null">
                  {{
                    $t('paymentPlans.intervalDescription', {
                      currency: member.lockedCurrency.toUpperCase(),
                      amount: $n(
                        member.lockedCost / 100,
                        'currency',
                        siteLocaleCurrency
                      ),
                      interval: $tc(
                        `paymentPlans.interval.${member.lockedInterval.toLowerCase()}`,
                        member.lockedIntervalCount
                      ),
                    })
                  }}
                </span>
                <span v-else>—</span>
              </td>
              <td v-if="billingGroup.isPrimaryMember" class="text-right">
                <q-btn
                  v-if="!member.isPrimary"
                  flat
                  round
                  dense
                  color="negative"
                  icon="mdi-account-remove"
                  :title="$t('billingGroup.removeMember')"
                  @click="removeMember(member)"
                />
              </td>
            </tr>
          </tbody>
        </q-markup-table>

        <!-- Mobile list -->
        <q-list
          bordered
          padding
          class="rounded-borders desktop-hide"
          style="max-width: 350px"
        >
          <q-item v-for="member in billingGroup.members" :key="member.id">
            <q-item-section>
              <q-item-label lines="1">
                {{ member.name }}
                <q-chip
                  v-if="member.isPrimary"
                  dense
                  size="sm"
                  color="primary"
                  text-color="white"
                  class="q-ml-xs"
                >
                  {{ $t('billingGroup.isPrimary') }}
                </q-chip>
              </q-item-label>
              <q-item-label caption>
                <span v-if="member.lockedCost != null">
                  {{ member.addonName }} —
                  {{
                    $t('paymentPlans.intervalDescription', {
                      currency: member.lockedCurrency.toUpperCase(),
                      amount: $n(
                        member.lockedCost / 100,
                        'currency',
                        siteLocaleCurrency
                      ),
                      interval: $tc(
                        `paymentPlans.interval.${member.lockedInterval.toLowerCase()}`,
                        member.lockedIntervalCount
                      ),
                    })
                  }}
                </span>
                <span v-else>{{ $t('adminTools.noAddonCost') }}</span>
              </q-item-label>
            </q-item-section>
            <q-item-section
              side
              v-if="billingGroup.isPrimaryMember && !member.isPrimary"
            >
              <q-btn
                flat
                round
                dense
                color="negative"
                icon="mdi-account-remove"
                :title="$t('billingGroup.removeMember')"
                @click="removeMember(member)"
              />
            </q-item-section>
          </q-item>
        </q-list>

        <!-- Primary member: invite + manage invitations -->
        <template v-if="billingGroup.isPrimaryMember">
          <q-separator />
          <q-card-section>
            <div class="text-subtitle2 q-mb-sm">
              {{ $t('billingGroup.inviteMember') }}
            </div>
            <div class="row q-gutter-sm">
              <q-input
                v-model="inviteEmail"
                :label="$t('billingGroup.inviteMemberEmail')"
                outlined
                dense
                class="col"
                @keyup.enter="inviteMember"
              />
              <q-btn
                color="primary"
                :label="$t('billingGroup.inviteMember')"
                :loading="loadingInvite"
                :disable="!inviteEmail.trim()"
                @click="inviteMember"
              />
              <q-btn
                color="secondary"
                :label="$t('billingGroup.inviteNonmember')"
                :loading="loadingInviteNonmember"
                :disable="!inviteEmail.trim()"
                @click="inviteNonmember"
              />
            </div>
          </q-card-section>

          <!-- Pending invitations -->
          <template v-if="invitations.length">
            <q-separator />
            <q-card-section>
              <div class="text-subtitle2 q-mb-sm">
                {{ $t('billingGroup.pendingInvitations') }}
              </div>
              <q-list dense>
                <q-item v-for="inv in invitations" :key="inv.id">
                  <q-item-section>
                    <q-item-label>{{ inv.email }}</q-item-label>
                    <q-item-label caption>
                      {{ $t('billingGroup.invitationExpires') }}:
                      {{ formatDate(inv.expiresDate) }}
                    </q-item-label>
                  </q-item-section>
                  <q-item-section side>
                    <div class="row q-gutter-xs">
                      <q-btn
                        flat
                        dense
                        size="sm"
                        :label="$t('billingGroup.resendInvitation')"
                        @click="resendInvitation(inv.id)"
                      />
                      <q-btn
                        flat
                        dense
                        size="sm"
                        color="negative"
                        :label="$t('billingGroup.cancelInvitation')"
                        @click="cancelInvitation(inv.id)"
                      />
                    </div>
                  </q-item-section>
                </q-item>
              </q-list>
            </q-card-section>
          </template>

          <q-separator />
          <q-card-actions>
            <q-btn
              flat
              color="negative"
              :label="$t('billingGroup.deleteGroup')"
              :loading="loadingDelete"
              @click="deleteGroup"
            />
          </q-card-actions>
        </template>

        <!-- Secondary member: leave -->
        <template v-else>
          <q-separator />
          <q-card-actions>
            <q-btn
              flat
              color="negative"
              :label="$t('billingGroup.leaveGroup')"
              :loading="loadingLeave"
              @click="leaveGroup"
            />
          </q-card-actions>
        </template>
      </q-card>
    </template>

    <template v-else-if="!loading">
      <!-- Not in a group -->
      <p>{{ $t('billingGroup.noGroup') }}</p>
      <q-btn
        color="primary"
        :label="$t('billingGroup.createGroup')"
        :disable="!canCreate"
        @click="openCreateDialog"
      />
      <p v-if="!canCreate" class="text-caption text-negative q-mt-xs">
        {{ $t('billingGroup.requiresSubscription') }}
      </p>
    </template>
  </div>
</template>

<script lang="ts">
import { mapGetters } from 'vuex';
import CreateBillingGroupDialog from './CreateBillingGroupDialog.vue';

export default {
  name: 'BillingGroupManager',
  data() {
    return {
      loading: true,
      billingGroup: null as null | {
        id: number;
        name: string;
        isPrimaryMember: boolean;
        members: { id: number; name: string; isPrimary: boolean }[];
      },
      invitations: [] as { id: number; email: string; expiresDate: string }[],
      inviteEmail: '',
      loadingInvite: false,
      loadingInviteNonmember: false,
      loadingDelete: false,
      loadingLeave: false,
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    ...mapGetters('config', ['siteLocaleCurrency']),
    canCreate() {
      const status = this.profile?.financial?.subscriptionState;
      return status === 'active' || status === 'cancelling';
    },
  },
  async mounted() {
    await this.fetchGroup();
  },
  methods: {
    formatDate(dateStr: string) {
      return new Date(dateStr).toLocaleDateString('en-au');
    },
    async fetchGroup() {
      this.loading = true;
      try {
        const result = await this.$axios.get('/api/billing/billing-group/');
        if (result.data.success && result.data.billingGroup) {
          this.billingGroup = result.data.billingGroup;
          if (result.data.billingGroup.isPrimaryMember) {
            await this.fetchInvitations();
          }
        }
      } catch {
        // no group
      } finally {
        this.loading = false;
      }
    },
    async fetchInvitations() {
      try {
        const result = await this.$axios.get(
          '/api/billing/billing-group/invitations/'
        );
        this.invitations = Array.isArray(result.data) ? result.data : [];
      } catch {
        this.invitations = [];
      }
    },
    openCreateDialog() {
      this.$q
        .dialog({ component: CreateBillingGroupDialog })
        .onOk(() => this.fetchGroup());
    },
    async inviteMember() {
      if (!this.inviteEmail.trim()) return;
      this.loadingInvite = true;
      try {
        const result = await this.$axios.post(
          '/api/billing/billing-group/members/',
          { email: this.inviteEmail.trim() }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.inviteMemberSent'),
          });
          this.inviteEmail = '';
          await this.fetchGroup();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.inviteMemberFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.inviteMemberFailed'),
        });
      } finally {
        this.loadingInvite = false;
      }
    },
    async inviteNonmember() {
      if (!this.inviteEmail.trim()) return;
      this.loadingInviteNonmember = true;
      try {
        const result = await this.$axios.post(
          '/api/billing/billing-group/invite-nonmember/',
          { email: this.inviteEmail.trim() }
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.inviteNonmemberSent'),
          });
          this.inviteEmail = '';
          await this.fetchInvitations();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.inviteNonmemberFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.inviteNonmemberFailed'),
        });
      } finally {
        this.loadingInviteNonmember = false;
      }
    },
    removeMember(member: { id: number; name: string }) {
      this.$q
        .dialog({
          title: this.$t('billingGroup.removeMember'),
          message: this.$t('billingGroup.removeMemberConfirm', {
            name: member.name,
          }),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          try {
            const result = await this.$axios.delete(
              '/api/billing/billing-group/members/',
              { data: { member_id: member.id } }
            );
            if (result.data.success) {
              this.$q.notify({
                type: 'positive',
                message: this.$t('billingGroup.removeMemberSuccess'),
              });
              await this.fetchGroup();
            } else {
              this.$q.notify({
                type: 'negative',
                message: this.$t('billingGroup.removeMemberFailed'),
              });
            }
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('billingGroup.removeMemberFailed'),
            });
          }
        });
    },
    deleteGroup() {
      this.$q
        .dialog({
          title: this.$t('billingGroup.deleteGroup'),
          message: this.$t('billingGroup.deleteGroupConfirm'),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          this.loadingDelete = true;
          try {
            const result = await this.$axios.delete(
              '/api/billing/billing-group/'
            );
            if (result.data.success) {
              this.$q.notify({
                type: 'positive',
                message: this.$t('billingGroup.deleteGroupSuccess'),
              });
              this.billingGroup = null;
            } else {
              this.$q.notify({
                type: 'negative',
                message: this.$t('billingGroup.deleteGroupFailed'),
              });
            }
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('billingGroup.deleteGroupFailed'),
            });
          } finally {
            this.loadingDelete = false;
          }
        });
    },
    leaveGroup() {
      this.$q
        .dialog({
          title: this.$t('billingGroup.leaveGroup'),
          message: this.$t('billingGroup.leaveGroupConfirm'),
          cancel: this.$t('button.cancel'),
          persistent: true,
        })
        .onOk(async () => {
          this.loadingLeave = true;
          try {
            const result = await this.$axios.post(
              '/api/billing/billing-group/leave/'
            );
            if (result.data.success) {
              this.$q.notify({
                type: 'positive',
                message: this.$t('billingGroup.leaveGroupSuccess'),
              });
              this.billingGroup = null;
            } else {
              this.$q.notify({
                type: 'negative',
                message: this.$t('billingGroup.leaveGroupFailed'),
              });
            }
          } catch {
            this.$q.notify({
              type: 'negative',
              message: this.$t('billingGroup.leaveGroupFailed'),
            });
          } finally {
            this.loadingLeave = false;
          }
        });
    },
    async resendInvitation(id: number) {
      try {
        const result = await this.$axios.post(
          `/api/billing/billing-group/invitations/${id}/resend/`
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.resendSuccess'),
          });
          await this.fetchInvitations();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.resendFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.resendFailed'),
        });
      }
    },
    async cancelInvitation(id: number) {
      try {
        const result = await this.$axios.delete(
          `/api/billing/billing-group/invitations/${id}/cancel/`
        );
        if (result.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billingGroup.cancelInvitationSuccess'),
          });
          await this.fetchInvitations();
        } else {
          this.$q.notify({
            type: 'negative',
            message: this.$t('billingGroup.cancelInvitationFailed'),
          });
        }
      } catch {
        this.$q.notify({
          type: 'negative',
          message: this.$t('billingGroup.cancelInvitationFailed'),
        });
      }
    },
  },
};
</script>
