<template>
  <div class="billing-group-manager">
    <!-- Create Billing Group Button -->
    <div v-if="!billingGroup && !pendingInvite" class="q-mb-md">
      <q-btn
        :label="$t('adminTools.createBillingGroup')"
        color="primary"
        @click="showCreateDialog = true"
      />
    </div>

    <!-- Pending Invite -->
    <div v-if="pendingInvite" class="q-mb-md">
      <q-banner class="bg-info text-white">
        <div class="text-h6">{{ $t('billing.pendingInvite') }}</div>
        <p>{{ $t('billing.invitedToGroup', { name: pendingInvite.name }) }}</p>
        <div class="row q-gutter-sm q-mt-md">
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

    <!-- Billing Group Info -->
    <div v-if="billingGroup" class="q-mb-md">
      <q-card>
        <q-card-section>
          <div class="text-h6">{{ billingGroup.name }}</div>
          <div class="text-subtitle2 q-mt-sm">
            {{ $t('adminTools.primaryMember') }}:
            {{ billingGroup.primary_member?.name || $t('error.noValue') }}
          </div>
        </q-card-section>

        <q-card-section v-if="billingGroup.is_primary">
          <div class="text-h6 q-mb-md">{{ $t('billing.members') }}</div>

          <q-table
            :rows="billingGroup.members"
            :columns="memberColumns"
            row-key="id"
            :pagination="{ rowsPerPage: 0 }"
            flat
            bordered
          >
            <template v-slot:body-cell-status="props">
              <q-td :props="props">
                <q-chip
                  :color="
                    props.row.status === 'member' ? 'positive' : 'warning'
                  "
                  :label="
                    props.row.status === 'member'
                      ? $t('billing.statusMember')
                      : $t('billing.statusInvited')
                  "
                  text-color="white"
                  size="sm"
                />
              </q-td>
            </template>
            <template v-slot:body-cell-locked_pricing="props">
              <q-td :props="props">
                <!-- Show --- for the primary member (owner) -->
                <div
                  v-if="props.row.id === billingGroup.primary_member?.id"
                  class="text-grey-6"
                >
                  ---
                </div>
                <!-- Show locked pricing for other members -->
                <div
                  v-else-if="
                    props.row.locked_addon_pricing &&
                    props.row.locked_addon_pricing.length > 0
                  "
                >
                  <div
                    v-for="addon in props.row.locked_addon_pricing"
                    :key="addon.addon_id"
                    class="q-mb-xs"
                  >
                    <q-chip
                      size="sm"
                      color="primary"
                      text-color="white"
                      :label="`${addon.addon_name}: ${addon.locked_pricing.cost_display}/${addon.locked_pricing.interval}`"
                    />
                    <div class="text-caption text-grey-6">
                      {{ $t('billing.lockedOn') }}:
                      {{ formatDate(addon.locked_pricing.date_locked) }}
                    </div>
                  </div>
                </div>
                <div v-else class="text-grey-6">
                  {{ $t('billing.noLockedPricing') }}
                </div>
              </q-td>
            </template>
            <template v-slot:body-cell-actions="props">
              <q-td :props="props">
                <q-btn
                  v-if="props.row.id !== profile.id"
                  :label="
                    props.row.status === 'member'
                      ? $t('billing.button.remove')
                      : $t('billing.button.cancelInvite')
                  "
                  color="negative"
                  size="sm"
                  @click="removeMember(props.row)"
                  :loading="loading"
                />
              </q-td>
            </template>
          </q-table>

          <div class="q-mt-md row q-gutter-sm">
            <q-btn
              :label="$t('billing.button.inviteMember')"
              color="primary"
              @click="showAddMemberDialog = true"
            />
            <q-btn
              v-if="canDeleteBillingGroup"
              :label="$t('billing.button.deleteBillingGroup')"
              color="negative"
              @click="showDeleteDialog = true"
              outline
            />
          </div>
        </q-card-section>

        <q-card-section v-else>
          <div class="text-body1">
            {{ $t('billing.memberOfGroup') }}
          </div>
        </q-card-section>
      </q-card>
    </div>

    <!-- Create Billing Group Dialog -->
    <q-dialog v-model="showCreateDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminTools.createBillingGroup') }}</div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="createBillingGroup" class="q-gutter-md">
            <q-input
              v-model="createForm.name"
              :label="$t('billing.groupName')"
              :rules="[(val) => !!val || $t('billing.groupNameRequired')]"
              outlined
              dense
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                :label="$t('billing.button.cancel')"
                color="grey"
                @click="showCreateDialog = false"
                flat
              />
              <q-btn
                :label="$t('billing.button.create')"
                type="submit"
                color="primary"
                :loading="loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Invite Member Dialog -->
    <q-dialog v-model="showAddMemberDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('billing.inviteMember') }}</div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="addMember" class="q-gutter-md">
            <q-input
              v-model="addMemberForm.email"
              :label="$t('billing.memberEmail')"
              :rules="[(val) => !!val || $t('billing.emailRequired')]"
              outlined
              dense
              type="email"
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                :label="$t('billing.button.cancel')"
                color="grey"
                @click="showAddMemberDialog = false"
                flat
              />
              <q-btn
                :label="$t('billing.button.add')"
                type="submit"
                color="primary"
                :loading="loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Delete Billing Group Dialog -->
    <q-dialog v-model="showDeleteDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('billing.deleteBillingGroup') }}</div>
        </q-card-section>

        <q-card-section>
          <div class="text-body1 q-mb-md">
            {{
              $t('billing.deleteBillingGroupConfirm', {
                name: billingGroup?.name,
              })
            }}
          </div>
          <div class="text-body2 text-warning">
            {{ $t('billing.deleteBillingGroupWarning') }}
          </div>
        </q-card-section>

        <q-card-section class="row justify-end q-gutter-sm">
          <q-btn
            :label="$t('billing.button.cancel')"
            color="grey"
            @click="showDeleteDialog = false"
            flat
          />
          <q-btn
            :label="$t('billing.button.deleteBillingGroupConfirm')"
            color="negative"
            @click="deleteBillingGroup"
            :loading="loading"
          />
        </q-card-section>
      </q-card>
    </q-dialog>
  </div>
</template>

<script>
import { defineComponent } from 'vue';
import { mapGetters } from 'vuex';

export default defineComponent({
  name: 'BillingGroupManager',
  data() {
    return {
      loading: false,
      showCreateDialog: false,
      showAddMemberDialog: false,
      showDeleteDialog: false,
      billingGroup: null,
      pendingInvite: null,
      createForm: {
        name: '',
      },
      addMemberForm: {
        email: '',
      },
      memberColumns: [
        {
          name: 'name',
          label: this.$t('adminTools.billingGroupMemberName'),
          field: 'name',
          sortable: true,
        },
        {
          name: 'email',
          label: this.$t('billing.memberEmail'),
          field: 'email',
          sortable: true,
        },
        {
          name: 'status',
          label: this.$t('billing.memberStatus'),
          field: 'status',
          sortable: true,
        },
        {
          name: 'locked_pricing',
          label: this.$t('billing.lockedAddonPricing'),
          field: 'locked_addon_pricing',
          sortable: false,
        },
        {
          name: 'actions',
          label: this.$t('billing.button.actions'),
          field: 'actions',
        },
      ],
    };
  },
  computed: {
    ...mapGetters('profile', ['profile']),
    canDeleteBillingGroup() {
      // Can only delete if user is primary member and there's only one member (the owner)
      return (
        this.billingGroup?.is_primary &&
        this.billingGroup?.members?.length === 1
      );
    },
  },
  methods: {
    formatDate(dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return date.toLocaleDateString();
    },

    async loadBillingGroupInfo() {
      try {
        const response = await this.$axios.get('/api/billing/billing-group/');
        if (response.data.success) {
          this.billingGroup = response.data.billing_group;
          this.pendingInvite = response.data.pending_invite;
        }
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: this.$t('error.requestFailed'),
        });
      }
    },

    async createBillingGroup() {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          '/api/billing/billing-group/',
          this.createForm
        );
        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billing.groupCreated'),
          });
          this.showCreateDialog = false;
          this.createForm.name = '';
          await this.loadBillingGroupInfo();
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

    async addMember() {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          '/api/billing/billing-group/members/',
          this.addMemberForm
        );
        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billing.memberAdded'),
          });
          this.showAddMemberDialog = false;
          this.addMemberForm.email = '';
          await this.loadBillingGroupInfo();
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

    async removeMember(member) {
      this.loading = true;
      try {
        const response = await this.$axios.delete(
          '/api/billing/billing-group/members/',
          {
            data: { member_id: member.id },
          }
        );
        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billing.memberRemoved'),
          });
          await this.loadBillingGroupInfo();
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

    async respondToInvite(action) {
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
          await this.loadBillingGroupInfo();
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

    async deleteBillingGroup() {
      this.loading = true;
      try {
        const response = await this.$axios.delete(
          '/api/billing/billing-group/'
        );
        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('billing.billingGroupDeleted'),
          });
          this.showDeleteDialog = false;
          await this.loadBillingGroupInfo();
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
    this.loadBillingGroupInfo();
  },
});
</script>
