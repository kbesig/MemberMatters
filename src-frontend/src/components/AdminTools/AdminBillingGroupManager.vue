<template>
  <div class="admin-billing-group-manager">
    <!-- Header with group info and actions -->
    <div class="row justify-between items-center q-mb-md">
      <div>
        <div class="text-h6">{{ billingGroupData.name }}</div>
        <div class="text-subtitle2">
          {{ $t('adminTools.primaryMember') }}:
          <router-link
            v-if="billingGroupData.primary_member"
            :to="{
              name: 'manageMember',
              params: { memberId: billingGroupData.primary_member.id },
            }"
            class="text-primary"
          >
            {{ billingGroupData.primary_member.name }}
          </router-link>
          <span v-else>{{ $t('error.noValue') }}</span>
        </div>
      </div>
      <div class="row q-gutter-sm">
        <q-btn
          :label="$t('adminTools.addMember')"
          color="primary"
          @click="showAddMemberDialog = true"
        />
        <q-btn
          :label="$t('adminTools.editBillingGroup')"
          color="secondary"
          @click="showEditDialog = true"
        />
        <q-btn
          v-if="canDeleteBillingGroup"
          :label="$t('adminTools.deleteBillingGroup')"
          color="negative"
          outline
          @click="showDeleteDialog = true"
        />
      </div>
    </div>

    <!-- Members table -->
    <div class="text-h6 q-mb-md">
      {{ $t('adminTools.billingGroupMembers') }}
    </div>

    <q-table
      :rows="allMembers"
      :columns="memberColumns"
      row-key="id"
      :pagination="{ rowsPerPage: 10 }"
      :loading="loading"
      flat
      bordered
    >
      <template v-slot:body-cell-status="props">
        <q-td :props="props">
          <q-chip
            :color="getStatusColor(props.value)"
            :label="getStatusLabel(props.value)"
            size="sm"
          />
        </q-td>
      </template>

      <template v-slot:body-cell-actions="props">
        <q-td :props="props">
          <q-btn
            v-if="
              props.row.status === 'member' &&
              props.row.id !== billingGroupData.primary_member?.id
            "
            :label="$t('adminTools.removeMember')"
            size="sm"
            color="negative"
            flat
            round
            @click="removeMember(props.row)"
            :loading="loading"
          >
          </q-btn>
          <q-btn
            v-else-if="props.row.status === 'invited'"
            :label="$t('adminTools.cancelInvite')"
            size="sm"
            color="orange"
            flat
            round
            @click="cancelInvite(props.row)"
            :loading="loading"
          >
          </q-btn>
          <span v-else class="text-grey-6">{{
            $t('adminTools.primaryMember')
          }}</span>
        </q-td>
      </template>
    </q-table>

    <!-- Add Member Dialog -->
    <q-dialog v-model="showAddMemberDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">
            {{ $t('adminTools.addMemberToBillingGroup') }}
          </div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="addMember" class="q-gutter-md">
            <q-select
              v-model="addMemberForm.member_id"
              :options="availableMembers"
              :label="$t('adminTools.selectMember')"
              outlined
              dense
              clearable
              emit-value
              map-options
              option-value="id"
              option-label="name"
              use-input
              input-debounce="300"
              @filter="filterMembers"
              :rules="[(val) => !!val || $t('adminTools.memberRequired')]"
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                :label="$t('button.cancel')"
                color="grey"
                @click="showAddMemberDialog = false"
                flat
              />
              <q-btn
                :label="$t('button.add')"
                type="submit"
                color="primary"
                :loading="loading"
              />
            </div>
          </q-form>
        </q-card-section>
      </q-card>
    </q-dialog>

    <!-- Edit Billing Group Dialog -->
    <q-dialog v-model="showEditDialog" persistent>
      <q-card style="min-width: 400px">
        <q-card-section>
          <div class="text-h6">{{ $t('adminTools.editBillingGroup') }}</div>
        </q-card-section>

        <q-card-section>
          <q-form @submit="updateBillingGroup" class="q-gutter-md">
            <q-input
              v-model="editForm.name"
              :label="$t('adminTools.billingGroupName')"
              :rules="[
                (val) => !!val || $t('adminTools.billingGroupNameRequired'),
              ]"
              outlined
              dense
            />

            <div class="row justify-end q-gutter-sm">
              <q-btn
                :label="$t('button.cancel')"
                color="grey"
                @click="showEditDialog = false"
                flat
              />
              <q-btn
                :label="$t('button.update')"
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
          <div class="text-h6">{{ $t('adminTools.deleteBillingGroup') }}</div>
        </q-card-section>

        <q-card-section>
          <div class="text-body1 q-mb-md">
            {{
              $t('adminTools.deleteBillingGroupConfirm', {
                name: billingGroupData.name,
              })
            }}
          </div>
          <div class="text-body2 text-warning">
            {{ $t('adminTools.deleteBillingGroupWarning') }}
          </div>
        </q-card-section>

        <q-card-section class="row justify-end q-gutter-sm">
          <q-btn
            :label="$t('button.cancel')"
            color="grey"
            @click="showDeleteDialog = false"
            flat
          />
          <q-btn
            :label="$t('adminTools.deleteBillingGroupConfirm')"
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

export default defineComponent({
  name: 'AdminBillingGroupManager',
  props: {
    billingGroupId: {
      type: Number,
      required: true,
    },
  },
  emits: ['billing-group-updated', 'billing-group-deleted'],
  data() {
    return {
      loading: false,
      billingGroupData: {
        id: null,
        name: '',
        primary_member: null,
        members: [],
        invites: [],
      },
      allMembers: [],
      availableMembers: [],
      allMembersOptions: [],
      showAddMemberDialog: false,
      showEditDialog: false,
      showDeleteDialog: false,
      addMemberForm: {
        member_id: null,
      },
      editForm: {
        name: '',
      },
      memberColumns: [
        {
          name: 'name',
          label: this.$t('adminTools.memberName'),
          field: 'name',
          sortable: true,
          align: 'left',
        },
        {
          name: 'email',
          label: this.$t('adminTools.email'),
          field: 'email',
          sortable: true,
          align: 'left',
        },
        {
          name: 'status',
          label: this.$t('adminTools.status'),
          field: 'status',
          sortable: true,
          align: 'center',
        },
        {
          name: 'actions',
          label: this.$t('adminTools.actions'),
          field: 'actions',
          align: 'center',
        },
      ],
    };
  },
  computed: {
    canDeleteBillingGroup() {
      // Only allow deletion if there are no secondary members (only primary member remains)
      const secondaryMembers = this.billingGroupData.members.filter(
        (member) => member.id !== this.billingGroupData.primary_member?.id
      );
      const pendingInvites = this.billingGroupData.invites || [];

      return secondaryMembers.length === 0 && pendingInvites.length === 0;
    },
  },
  async mounted() {
    await this.loadBillingGroupData();
    await this.loadAvailableMembers();
  },
  methods: {
    async loadBillingGroupData() {
      this.loading = true;
      try {
        const response = await this.$axios.get(
          `/api/admin/billing-groups/${this.billingGroupId}/`
        );
        this.billingGroupData = response.data;

        // Combine members and invites for the table
        this.allMembers = [
          ...this.billingGroupData.members.map((member) => ({
            ...member,
            status: 'member',
          })),
          ...this.billingGroupData.invites.map((invite) => ({
            ...invite,
            status: 'invited',
          })),
        ];

        // Set edit form values
        this.editForm.name = this.billingGroupData.name;
      } catch (error) {
        this.$q.notify({
          type: 'negative',
          message: this.$t('error.requestFailed'),
        });
      } finally {
        this.loading = false;
      }
    },

    async loadAvailableMembers() {
      try {
        const response = await this.$axios.get('/api/admin/members/');
        this.allMembersOptions = response.data
          .filter(
            (member) =>
              // Exclude members already in this billing group or with other billing groups
              !member.billingGroup &&
              !this.allMembers.some((existing) => existing.id === member.id)
          )
          .map((member) => ({
            id: member.id,
            name: member.name.full,
            email: member.email,
          }));
        this.availableMembers = [...this.allMembersOptions];
      } catch (error) {
        console.error('Failed to load available members:', error);
      }
    },

    filterMembers(val, update) {
      update(() => {
        if (val === '') {
          this.availableMembers = [...this.allMembersOptions];
        } else {
          const needle = val.toLowerCase();
          this.availableMembers = this.allMembersOptions.filter(
            (member) =>
              member.name.toLowerCase().includes(needle) ||
              member.email.toLowerCase().includes(needle)
          );
        }
      });
    },

    async addMember() {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          `/api/admin/billing-groups/${this.billingGroupId}/members/`,
          {
            action: 'add',
            member_id: this.addMemberForm.member_id,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.memberAddedToBillingGroup'),
          });
          this.showAddMemberDialog = false;
          this.addMemberForm.member_id = null;
          await this.loadBillingGroupData();
          await this.loadAvailableMembers();
          this.$emit('billing-group-updated');
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
        const response = await this.$axios.post(
          `/api/admin/billing-groups/${this.billingGroupId}/members/`,
          {
            action: 'remove',
            member_id: member.id,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.memberRemovedFromBillingGroup'),
          });
          await this.loadBillingGroupData();
          await this.loadAvailableMembers();
          this.$emit('billing-group-updated');
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

    async cancelInvite(invite) {
      this.loading = true;
      try {
        const response = await this.$axios.post(
          `/api/admin/billing-groups/${this.billingGroupId}/invites/`,
          {
            action: 'cancel',
            member_id: invite.id,
          }
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.inviteCancelled'),
          });
          await this.loadBillingGroupData();
          await this.loadAvailableMembers();
          this.$emit('billing-group-updated');
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

    async updateBillingGroup() {
      this.loading = true;
      try {
        const response = await this.$axios.put(
          `/api/admin/billing-groups/${this.billingGroupId}/`,
          this.editForm
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.billingGroupUpdated'),
          });
          this.showEditDialog = false;
          await this.loadBillingGroupData();
          this.$emit('billing-group-updated');
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
          `/api/admin/billing-groups/${this.billingGroupId}/`
        );

        if (response.data.success) {
          this.$q.notify({
            type: 'positive',
            message: this.$t('adminTools.billingGroupDeleted'),
          });
          this.showDeleteDialog = false;
          this.$emit('billing-group-deleted');
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

    getStatusColor(status) {
      switch (status) {
        case 'member':
          return 'positive';
        case 'invited':
          return 'orange';
        default:
          return 'grey';
      }
    },

    getStatusLabel(status) {
      switch (status) {
        case 'member':
          return this.$t('adminTools.member');
        case 'invited':
          return this.$t('adminTools.invited');
        default:
          return status;
      }
    },
  },
});
</script>

<style scoped>
.admin-billing-group-manager {
  width: 100%;
}
</style>
